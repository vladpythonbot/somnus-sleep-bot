import 'dart:async';
import 'dart:convert';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter_health_connect/flutter_health_connect.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:workmanager/workmanager.dart';

const String appBuild = '2026-06-28-auto-sync-diagnostics';
const String backendUrl = 'https://somnus-sleep-bot-production.up.railway.app/webhook/sleep-apk';
const String sleepTaskName = 'sleep_daily_sync';
const String sleepTaskUniqueName = 'sleep_daily_sync_unique';
const int defaultReportDelayMinutes = 30;

const List<HealthConnectDataType> sleepTypes = [
  HealthConnectDataType.SleepSession,
  HealthConnectDataType.SleepStage,
];

@pragma('vm:entry-point')
void callbackDispatcher() {
  Workmanager().executeTask((task, inputData) async {
    DartPluginRegistrant.ensureInitialized();

    if (task != sleepTaskName && task != sleepTaskUniqueName) {
      return true;
    }

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('lastAutoRunAt', DateTime.now().toIso8601String());
    await prefs.setString('lastAutoRunTask', task);
    await prefs.remove('lastAutoError');

    final telegramId =
        inputData?['telegramId'] as String? ?? prefs.getString('telegramId') ?? '';
    final secret = inputData?['secret'] as String? ?? prefs.getString('secret') ?? '';
    final reportDelayMinutes = inputData?['reportDelayMinutes'] as int? ??
        prefs.getInt('reportDelayMinutes') ??
        defaultReportDelayMinutes;

    if (telegramId.isEmpty) {
      await prefs.setString('lastAutoSkipReason', 'empty_telegram_id');
      return false;
    }

    try {
      final payload = await collectSleepPayload(telegramId);
      await prefs.setString('lastAutoPayloadDate', sleepDateKey(payload));
      final shouldSend = await shouldSendAfterWake(
        payload: payload,
        delayMinutes: reportDelayMinutes,
        prefs: prefs,
      );
      if (!shouldSend) {
        await prefs.setString(
          'lastAutoSkipReason',
          automaticSkipReason(payload, reportDelayMinutes, prefs),
        );
        return true;
      }

      await sendSleepPayload(
        backendUrl: backendUrl,
        secret: secret,
        payload: payload,
      );
      await markScheduledReportSent(prefs, payload);
      await prefs.setString('lastAutoSkipReason', 'sent');
      return true;
    } catch (error) {
      await prefs.setString('lastAutoError', error.toString());
      await prefs.setString('lastAutoSkipReason', 'error');
      return false;
    }
  });
}

String todayKey() {
  final now = DateTime.now();
  return '${now.year.toString().padLeft(4, '0')}-'
      '${now.month.toString().padLeft(2, '0')}-'
      '${now.day.toString().padLeft(2, '0')}';
}

DateTime? parseIsoDate(String? value) {
  if (value == null || value.isEmpty) {
    return null;
  }
  return DateTime.tryParse(value);
}

String sleepDateKey(Map<String, dynamic> payload) {
  final sleepEnd = parseIsoDate(payload['sleep_end'] as String?);
  if (sleepEnd == null) {
    return todayKey();
  }
  return '${sleepEnd.year.toString().padLeft(4, '0')}-'
      '${sleepEnd.month.toString().padLeft(2, '0')}-'
      '${sleepEnd.day.toString().padLeft(2, '0')}';
}

Future<bool> shouldSendAfterWake({
  required Map<String, dynamic> payload,
  required int delayMinutes,
  required SharedPreferences prefs,
}) async {
  final sleepEnd = parseIsoDate(payload['sleep_end'] as String?);
  if (sleepEnd == null) {
    return false;
  }

  final readyAt = sleepEnd.add(Duration(minutes: delayMinutes));
  if (DateTime.now().isBefore(readyAt)) {
    return false;
  }

  return prefs.getString('lastAutoSentSleepDate') != sleepDateKey(payload);
}

String automaticSkipReason(
  Map<String, dynamic> payload,
  int delayMinutes,
  SharedPreferences prefs,
) {
  final sleepEnd = parseIsoDate(payload['sleep_end'] as String?);
  if (sleepEnd == null) {
    return 'no_sleep_end';
  }

  final readyAt = sleepEnd.add(Duration(minutes: delayMinutes));
  if (DateTime.now().isBefore(readyAt)) {
    return 'too_early_until_${readyAt.toIso8601String()}';
  }

  if (prefs.getString('lastAutoSentSleepDate') == sleepDateKey(payload)) {
    return 'already_sent_${sleepDateKey(payload)}';
  }

  return 'unknown';
}

Future<void> markScheduledReportSent(SharedPreferences prefs, Map<String, dynamic> payload) async {
  await prefs.setString('lastAutoSentSleepDate', sleepDateKey(payload));
}

Future<Map<String, dynamic>> collectSleepPayload(String telegramId) async {
  final now = DateTime.now();
  final startTime = now.subtract(const Duration(days: 7));

  final sessionRecords = await HealthConnectFactory.getRecord(
    type: HealthConnectDataType.SleepSession,
    startTime: startTime,
    endTime: now,
  );
  final stageRecords = await HealthConnectFactory.getRecord(
    type: HealthConnectDataType.SleepStage,
    startTime: startTime,
    endTime: now,
  );

  final sleepWindow = findLatestSleepWindow(sessionRecords);
  final parsed = parseSleepRecords(
    [sessionRecords, stageRecords],
    windowStart: sleepWindow?.start,
    windowEnd: sleepWindow?.end,
  );
  final debug = Map<String, dynamic>.from(parsed.debug)
    ..addAll({
      'read_window_days': 7,
      'session_record_count': countRecordLikeItems(sessionRecords),
      'stage_record_count': countRecordLikeItems(stageRecords),
      'selected_sleep_start': sleepWindow?.start.toIso8601String(),
      'selected_sleep_end': sleepWindow?.end.toIso8601String(),
      'session_sample': compactDebugSample(sessionRecords),
      'stage_sample': compactDebugSample(stageRecords),
    });

  return {
    'telegram_id': int.tryParse(telegramId) ?? telegramId,
    'date': now.toIso8601String(),
    'source': 'health_connect_flutter_apk',
    'app_build': appBuild,
    'sleep_start': parsed.sleepStart?.toIso8601String(),
    'sleep_end': parsed.sleepEnd?.toIso8601String(),
    'total_sleep_minutes': parsed.totalSleepMinutes,
    'deep_sleep_minutes': parsed.deepSleepMinutes,
    'light_sleep_minutes': parsed.lightSleepMinutes,
    'rem_sleep_minutes': parsed.remSleepMinutes,
    'awake_minutes': parsed.awakeMinutes,
    'raw_debug': debug,
  };
}

Future<void> sendSleepPayload({
  required String backendUrl,
  required String secret,
  required Map<String, dynamic> payload,
}) async {
  final response = await http.post(
    Uri.parse(backendUrl),
    headers: {
      'Content-Type': 'application/json',
      if (secret.isNotEmpty) 'X-Webhook-Secret': secret,
    },
    body: jsonEncode(payload),
  );

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw Exception('Backend error: ${response.statusCode} ${response.body}');
  }
}

class ParsedSleep {
  const ParsedSleep({
    required this.totalSleepMinutes,
    required this.deepSleepMinutes,
    required this.lightSleepMinutes,
    required this.remSleepMinutes,
    required this.awakeMinutes,
    required this.sleepStart,
    required this.sleepEnd,
    required this.debug,
  });

  final int totalSleepMinutes;
  final int deepSleepMinutes;
  final int lightSleepMinutes;
  final int remSleepMinutes;
  final int awakeMinutes;
  final DateTime? sleepStart;
  final DateTime? sleepEnd;
  final Map<String, dynamic> debug;
}

class SleepWindow {
  const SleepWindow({required this.start, required this.end});

  final DateTime start;
  final DateTime end;
}

ParsedSleep parseSleepRecords(
  dynamic records, {
  DateTime? windowStart,
  DateTime? windowEnd,
}) {
  var deep = 0;
  var light = 0;
  var rem = 0;
  var awake = 0;
  var sessionTotal = 0;
  var visitedMaps = 0;
  var durationRecords = 0;
  var classifiedStageRecords = 0;
  var unclassifiedDurationRecords = 0;
  DateTime? sleepStart = windowStart;
  DateTime? sleepEnd = windowEnd;

  void visit(dynamic value) {
    if (value is List) {
      for (final item in value) {
        visit(item);
      }
      return;
    }

    if (value is Map) {
      visitedMaps += 1;
      final map = value.map((key, item) => MapEntry(key.toString(), item));
      final typeText = map.values.join(' ').toLowerCase();
      final minutes = extractDurationMinutes(map);
      final stage = classifySleepStage(map, typeText);
      final start = extractStartTime(map);
      final end = extractEndTime(map);
      final insideSelectedWindow = isInsideWindow(start, end, windowStart, windowEnd);
      final minutesInWindow = minutesInsideWindow(start, end, windowStart, windowEnd);

      if (minutes > 0) {
        durationRecords += 1;
        if (stage == 'sleep' && start != null && end != null && sleepStart == null && sleepEnd == null) {
          if (sleepStart == null || start.isBefore(sleepStart!)) {
            sleepStart = start;
          }
          if (sleepEnd == null || end.isAfter(sleepEnd!)) {
            sleepEnd = end;
          }
        }
        switch (stage) {
          case 'deep':
            if (!insideSelectedWindow) {
              break;
            }
            deep += minutesInWindow > 0 ? minutesInWindow : minutes;
            classifiedStageRecords += 1;
            break;
          case 'rem':
            if (!insideSelectedWindow) {
              break;
            }
            rem += minutesInWindow > 0 ? minutesInWindow : minutes;
            classifiedStageRecords += 1;
            break;
          case 'light':
            if (!insideSelectedWindow) {
              break;
            }
            light += minutesInWindow > 0 ? minutesInWindow : minutes;
            classifiedStageRecords += 1;
            break;
          case 'awake':
            if (!insideSelectedWindow) {
              break;
            }
            awake += minutesInWindow > 0 ? minutesInWindow : minutes;
            classifiedStageRecords += 1;
            break;
          case 'sleep':
            if (insideSelectedWindow) {
              sessionTotal += minutesInWindow > 0 ? minutesInWindow : minutes;
            }
            break;
          default:
            unclassifiedDurationRecords += 1;
        }
      }

      for (final child in map.values) {
        if (child is List || child is Map) {
          visit(child);
        }
      }
    }
  }

  visit(records);

  final stageTotal = deep + light + rem;
  final total = stageTotal > 0 ? stageTotal : sessionTotal;

  return ParsedSleep(
    totalSleepMinutes: total,
    deepSleepMinutes: deep,
    lightSleepMinutes: light,
    remSleepMinutes: rem,
    awakeMinutes: awake,
    sleepStart: sleepStart,
    sleepEnd: sleepEnd,
    debug: {
      'stage_total': stageTotal,
      'session_total': sessionTotal,
      'visited_maps': visitedMaps,
      'duration_records': durationRecords,
      'classified_stage_records': classifiedStageRecords,
      'unclassified_duration_records': unclassifiedDurationRecords,
    },
  );
}

SleepWindow? findLatestSleepWindow(dynamic records) {
  SleepWindow? selected;
  var selectedMinutes = 0;

  void visit(dynamic value) {
    if (value is List) {
      for (final item in value) {
        visit(item);
      }
      return;
    }
    if (value is Map) {
      final map = value.map((key, item) => MapEntry(key.toString(), item));
      final start = extractStartTime(map);
      final end = extractEndTime(map);
      final minutes = extractDurationMinutes(map);
      final hasStage = extractStageCode(map) != null;

      if (!hasStage && start != null && end != null && minutes >= 120 && minutes <= 16 * 60) {
        if (selected == null ||
            end.isAfter(selected!.end) ||
            (end.isAtSameMomentAs(selected!.end) && minutes > selectedMinutes)) {
          selected = SleepWindow(start: start, end: end);
          selectedMinutes = minutes;
        }
      }

      for (final child in map.values) {
        if (child is List || child is Map) {
          visit(child);
        }
      }
    }
  }

  visit(records);
  return selected;
}

bool isInsideWindow(DateTime? start, DateTime? end, DateTime? windowStart, DateTime? windowEnd) {
  if (windowStart == null || windowEnd == null) {
    return true;
  }
  if (start == null || end == null) {
    return false;
  }
  return end.isAfter(windowStart) && start.isBefore(windowEnd);
}

int minutesInsideWindow(DateTime? start, DateTime? end, DateTime? windowStart, DateTime? windowEnd) {
  if (start == null || end == null || windowStart == null || windowEnd == null) {
    return 0;
  }
  final clippedStart = start.isBefore(windowStart) ? windowStart : start;
  final clippedEnd = end.isAfter(windowEnd) ? windowEnd : end;
  final minutes = clippedEnd.difference(clippedStart).inMinutes;
  return minutes > 0 ? minutes : 0;
}

String? classifySleepStage(Map<String, dynamic> map, String typeText) {
  if (typeText.contains('deep')) {
    return 'deep';
  }
  if (typeText.contains('rem')) {
    return 'rem';
  }
  if (typeText.contains('light')) {
    return 'light';
  }
  if (typeText.contains('awake') ||
      typeText.contains('wake') ||
      typeText.contains('out_of_bed') ||
      typeText.contains('out of bed')) {
    return 'awake';
  }

  final stageCode = extractStageCode(map);
  switch (stageCode) {
    case 1: // Awake
    case 3: // Out of bed
      return 'awake';
    case 2: // Generic sleeping stage
      return 'sleep';
    case 4: // Light sleep
      return 'light';
    case 5: // Deep sleep
      return 'deep';
    case 6: // REM sleep
      return 'rem';
  }

  if (typeText.contains('sleep')) {
    return 'sleep';
  }
  return null;
}

int? extractStageCode(Map<String, dynamic> map) {
  final value = firstValue(map, [
    'stage',
    'stageType',
    'stage_type',
    'sleepStage',
    'sleep_stage',
    'sleepStageType',
    'sleep_stage_type',
    'type',
  ]);
  return parseStageCode(value);
}

int? parseStageCode(dynamic value) {
  if (value == null) {
    return null;
  }
  if (value is num) {
    return value.toInt();
  }
  if (value is Map) {
    final map = value.map((key, child) => MapEntry(key.toString(), child));
    return parseStageCode(firstValue(map, ['value', 'code', 'id', 'stage', 'name']));
  }
  final text = value.toString().toLowerCase();
  final direct = int.tryParse(text);
  if (direct != null) {
    return direct;
  }
  if (text.contains('awake') || text.contains('out_of_bed') || text.contains('out of bed')) {
    return 1;
  }
  if (text.contains('light')) {
    return 4;
  }
  if (text.contains('deep')) {
    return 5;
  }
  if (text.contains('rem')) {
    return 6;
  }
  if (text.contains('sleep')) {
    return 2;
  }
  return null;
}

int countRecordLikeItems(dynamic value) {
  var count = 0;

  void visit(dynamic item) {
    if (item is List) {
      for (final child in item) {
        visit(child);
      }
      return;
    }
    if (item is Map) {
      final map = item.map((key, child) => MapEntry(key.toString(), child));
      if (extractDurationMinutes(map) > 0 || extractStageCode(map) != null) {
        count += 1;
      }
      for (final child in map.values) {
        if (child is List || child is Map) {
          visit(child);
        }
      }
    }
  }

  visit(value);
  return count;
}

Map<String, dynamic> compactDebugSample(dynamic value) {
  Map<String, dynamic>? sample;

  void visit(dynamic item) {
    if (sample != null) {
      return;
    }
    if (item is List) {
      for (final child in item) {
        visit(child);
        if (sample != null) {
          return;
        }
      }
      return;
    }
    if (item is Map) {
      final map = item.map((key, child) => MapEntry(key.toString(), child));
      final records = map['records'];
      if (records is List) {
        visit(records);
        return;
      }

      final duration = extractDurationMinutes(map);
      final stageCode = extractStageCode(map);
      if (duration <= 0 && stageCode == null && map.values.any((child) => child is List || child is Map)) {
        for (final child in map.values) {
          if (child is List || child is Map) {
            visit(child);
            if (sample != null) {
              return;
            }
          }
        }
      }

      final keys = map.keys.take(12).toList();
      sample = {
        'keys': keys,
        'duration_minutes': duration,
        'stage_code': stageCode,
        'start_parsed': parseDate(firstValue(map, [
          'startTime',
          'start_time',
          'startDateTime',
          'start_date_time',
          'startTimeMillis',
          'start_time_millis',
        ]))?.toIso8601String(),
        'end_parsed': parseDate(firstValue(map, [
          'endTime',
          'end_time',
          'endDateTime',
          'end_date_time',
          'endTimeMillis',
          'end_time_millis',
        ]))?.toIso8601String(),
        'text': map.values.join(' ').replaceAll(RegExp(r'\s+'), ' ').trim(),
      };
    }
  }

  visit(value);
  if (sample == null) {
    return {'empty': true};
  }
  final text = sample!['text'].toString();
  if (text.length > 180) {
    sample!['text'] = '${text.substring(0, 180)}...';
  }
  return sample!;
}

int extractDurationMinutes(Map<String, dynamic> map) {
  final direct = firstValue(map, [
    'durationMinutes',
    'duration_minutes',
    'minutes',
    'duration',
    'durationMillis',
    'duration_millis',
    'durationSeconds',
    'duration_seconds',
  ]);

  final directMinutes = parseDurationMinutes(direct);
  if (directMinutes > 0) {
    return directMinutes;
  }

  final start = extractStartTime(map);
  final end = extractEndTime(map);

  if (start == null || end == null) {
    return 0;
  }

  final minutes = end.difference(start).inMinutes;
  if (minutes <= 0 || minutes > 24 * 60) {
    return 0;
  }
  return minutes;
}

DateTime? extractStartTime(Map<String, dynamic> map) {
  return parseDate(firstValue(map, [
    'startTime',
    'start_time',
    'startTimeMillis',
    'start_time_millis',
    'startEpochMillis',
    'start_epoch_millis',
    'startDateTime',
    'start_date_time',
    'startDate',
    'start_date',
    'start',
    'from',
  ]));
}

DateTime? extractEndTime(Map<String, dynamic> map) {
  return parseDate(firstValue(map, [
    'endTime',
    'end_time',
    'endTimeMillis',
    'end_time_millis',
    'endEpochMillis',
    'end_epoch_millis',
    'endDateTime',
    'end_date_time',
    'endDate',
    'end_date',
    'end',
    'to',
  ]));
}

int parseDurationMinutes(dynamic value) {
  if (value == null) {
    return 0;
  }
  if (value is Map) {
    final map = value.map((key, child) => MapEntry(key.toString(), child));
    return parseDurationMinutes(firstValue(map, [
      'minutes',
      'inMinutes',
      'seconds',
      'inSeconds',
      'millis',
      'milliseconds',
      'inMilliseconds',
      'value',
    ]));
  }
  if (value is num) {
    final number = value.toDouble();
    if (number <= 0) {
      return 0;
    }
    if (number < 24 * 60) {
      return number.round();
    }
    if (number < 24 * 60 * 60) {
      return (number / 60).round();
    }
    if (number < 24 * 60 * 60 * 1000) {
      return (number / 60000).round();
    }
    return 0;
  }

  final text = value.toString().trim();
  final parsed = num.tryParse(text);
  if (parsed != null) {
    return parseDurationMinutes(parsed);
  }

  final durationMatch = RegExp(r'^(\d+):(\d{1,2}):(\d{1,2})').firstMatch(text);
  if (durationMatch != null) {
    final hours = int.parse(durationMatch.group(1)!);
    final minutes = int.parse(durationMatch.group(2)!);
    final seconds = int.parse(durationMatch.group(3)!);
    return hours * 60 + minutes + (seconds >= 30 ? 1 : 0);
  }

  final minutesMatch = RegExp(r'(\d+)\s*(min|minute|minutes|м|мин)').firstMatch(text.toLowerCase());
  if (minutesMatch != null) {
    return int.parse(minutesMatch.group(1)!);
  }
  return 0;
}

dynamic firstValue(Map<String, dynamic> map, List<String> keys) {
  for (final key in keys) {
    if (map.containsKey(key) && map[key] != null) {
      return map[key];
    }
  }
  return null;
}

DateTime? parseDate(dynamic value) {
  if (value == null) {
    return null;
  }
  if (value is DateTime) {
    return value;
  }
  if (value is Map) {
    final map = value.map((key, child) => MapEntry(key.toString(), child));
    final epochSecond = firstValue(map, ['epochSecond', 'epoch_second', 'seconds', 'second']);
    if (epochSecond != null) {
      final seconds = num.tryParse(epochSecond.toString())?.toInt();
      if (seconds != null && seconds > 1000000000) {
        final nano = int.tryParse((firstValue(map, ['nano', 'nanos', 'nanosecond', 'nanoseconds']) ?? 0).toString()) ?? 0;
        return DateTime.fromMillisecondsSinceEpoch(seconds * 1000 + nano ~/ 1000000);
      }
    }
    return parseDate(firstValue(map, [
      'dateTime',
      'date_time',
      'time',
      'value',
      'millis',
      'milliseconds',
      'epochMillis',
      'epoch_millis',
      'epochMilliseconds',
      'epoch_milliseconds',
      'timestamp',
    ]));
  }
  if (value is num) {
    final number = value.toInt();
    if (number > 100000000000) {
      return DateTime.fromMillisecondsSinceEpoch(number);
    }
    if (number > 1000000000) {
      return DateTime.fromMillisecondsSinceEpoch(number * 1000);
    }
  }
  return DateTime.tryParse(value.toString());
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Workmanager().initialize(callbackDispatcher);
  runApp(const SomnusSyncApp());
}

class SomnusSyncApp extends StatelessWidget {
  const SomnusSyncApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Somnus',
      theme: ThemeData(
        colorSchemeSeed: Colors.indigo,
        useMaterial3: true,
      ),
      home: const SetupScreen(),
    );
  }
}

class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  final telegramController = TextEditingController();
  final secretController = TextEditingController();
  String status = 'Не запущено';
  int reportDelayMinutes = defaultReportDelayMinutes;

  @override
  void initState() {
    super.initState();
    loadSaved();
  }

  @override
  void dispose() {
    telegramController.dispose();
    secretController.dispose();
    super.dispose();
  }

  Future<void> loadSaved() async {
    final prefs = await SharedPreferences.getInstance();
    telegramController.text = prefs.getString('telegramId') ?? '';
    secretController.text = prefs.getString('secret') ?? '';
    final lastSent = prefs.getString('lastAutoSentSleepDate');
    final lastRun = prefs.getString('lastAutoRunAt');
    final lastReason = prefs.getString('lastAutoSkipReason');
    final lastError = prefs.getString('lastAutoError');

    final statusLines = <String>[];
    if (lastSent == null) {
      statusLines.add('Выбери задержку после подъёма и включи синхронизацию.');
    } else {
      statusLines.add('Последний автоотчёт: $lastSent');
    }
    if (lastRun != null) {
      statusLines.add('Фоновая проверка: ${formatStatusDateTime(lastRun)}');
    }
    if (lastReason != null) {
      statusLines.add('Статус проверки: ${formatAutoReason(lastReason)}');
    }
    if (lastError != null) {
      statusLines.add('Ошибка фона: $lastError');
    }

    setState(() {
      reportDelayMinutes = prefs.getInt('reportDelayMinutes') ?? defaultReportDelayMinutes;
      status = statusLines.join('\n');
    });
  }

  String formatStatusDateTime(String value) {
    final parsed = DateTime.tryParse(value);
    if (parsed == null) {
      return value;
    }
    final local = parsed.toLocal();
    return '${local.day.toString().padLeft(2, '0')}.'
        '${local.month.toString().padLeft(2, '0')} '
        '${local.hour.toString().padLeft(2, '0')}:'
        '${local.minute.toString().padLeft(2, '0')}';
  }

  String formatAutoReason(String value) {
    if (value == 'sent') {
      return 'отправлено';
    }
    if (value == 'no_sleep_end') {
      return 'сон найден, но без времени подъёма';
    }
    if (value.startsWith('too_early_until_')) {
      return 'ещё рано, ждём задержку после подъёма';
    }
    if (value.startsWith('already_sent_')) {
      return 'за эту ночь уже отправлено';
    }
    if (value == 'empty_telegram_id') {
      return 'не указан Telegram ID';
    }
    if (value == 'error') {
      return 'ошибка при фоновой отправке';
    }
    return value;
  }

  Future<void> pickReportDelay() async {
    final selected = await showModalBottomSheet<int>(
      context: context,
      builder: (context) {
        const values = [15, 30, 45, 60, 90];
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const ListTile(
                title: Text('Когда присылать отчёт'),
                subtitle: Text('После времени подъёма из Health Connect'),
              ),
              for (final value in values)
                ListTile(
                  title: Text('Через $value мин'),
                  trailing: value == reportDelayMinutes ? const Icon(Icons.check) : null,
                  onTap: () => Navigator.pop(context, value),
                ),
            ],
          ),
        );
      },
    );
    if (selected == null) {
      return;
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt('reportDelayMinutes', selected);
    setState(() {
      reportDelayMinutes = selected;
      status = 'Отчёт через $selected мин после подъёма. Нажми запуск, чтобы обновить расписание.';
    });
  }

  Future<void> start() async {
    try {
      setState(() => status = 'Проверяю Health Connect...');

      final isSupported = await HealthConnectFactory.isApiSupported();
      if (!isSupported) {
        setState(() => status = 'Health Connect не поддерживается на этом устройстве');
        return;
      }

      final isAvailable = await HealthConnectFactory.isAvailable();
      if (!isAvailable) {
        await HealthConnectFactory.installHealthConnect();
        setState(() => status = 'Установи Health Connect и повтори запуск');
        return;
      }

      setState(() => status = 'Запрашиваю разрешения...');

      final granted = await HealthConnectFactory.requestPermissions(
        sleepTypes,
        readOnly: true,
      );
      if (!granted) {
        setState(() => status = 'Разрешения не выданы');
        return;
      }

      final telegramId = telegramController.text.trim();
      final secret = secretController.text.trim();

      if (telegramId.isEmpty) {
        setState(() => status = 'Заполни Telegram ID');
        return;
      }

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('telegramId', telegramId);
      await prefs.setString('secret', secret);
      await prefs.setInt('reportDelayMinutes', reportDelayMinutes);

      await Workmanager().registerPeriodicTask(
        sleepTaskUniqueName,
        sleepTaskName,
        frequency: const Duration(minutes: 30),
        initialDelay: const Duration(minutes: 15),
        constraints: Constraints(networkType: NetworkType.connected),
        inputData: {
          'telegramId': telegramId,
          'secret': secret,
          'reportDelayMinutes': reportDelayMinutes,
        },
        existingWorkPolicy: ExistingPeriodicWorkPolicy.replace,
      );

      setState(() => status = 'Готово. Отчёт через $reportDelayMinutes мин после подъёма.');
    } catch (error) {
      setState(() => status = 'Ошибка запуска: $error');
    }
  }

  Future<void> testNow() async {
    final telegramId = telegramController.text.trim();

    if (telegramId.isEmpty) {
      setState(() => status = 'Заполни Telegram ID');
      return;
    }

    try {
      setState(() => status = 'Отправляю тест...');

      final payload = await collectSleepPayload(telegramId);
      await sendSleepPayload(
        backendUrl: backendUrl,
        secret: secretController.text.trim(),
        payload: payload,
      );

      setState(() => status = 'Тест отправлен. Автоотчёт придёт после подъёма + $reportDelayMinutes мин.');
    } catch (error) {
      setState(() => status = 'Ошибка теста: $error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Somnus'),
        centerTitle: false,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'Отчёт после пробуждения',
            style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 8),
          Text(
            'APK берёт сон из Health Connect и отправляет анализ в Telegram через выбранное время после подъёма.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 20),
          DecoratedBox(
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  Icon(Icons.cloud_done_outlined, color: theme.colorScheme.primary),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Сервер уже подключён. Вводить URL не нужно.',
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 20),
          TextField(
            controller: telegramController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Telegram ID',
              prefixIcon: Icon(Icons.telegram),
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: secretController,
            decoration: const InputDecoration(
              labelText: 'Webhook secret',
              prefixIcon: Icon(Icons.lock_outline),
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          DecoratedBox(
            decoration: BoxDecoration(
              border: Border.all(color: theme.colorScheme.outlineVariant),
              borderRadius: BorderRadius.circular(12),
            ),
            child: ListTile(
              leading: const Icon(Icons.schedule),
              title: const Text('Когда прислать отчёт'),
              subtitle: Text('Через $reportDelayMinutes мин после подъёма'),
              trailing: FilledButton.tonal(
                onPressed: pickReportDelay,
                child: Text('$reportDelayMinutes мин'),
              ),
            ),
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: start,
            style: FilledButton.styleFrom(
              minimumSize: const Size.fromHeight(48),
            ),
            child: const Text('Сохранить и включить'),
          ),
          const SizedBox(height: 12),
          OutlinedButton(
            onPressed: testNow,
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(48),
            ),
            child: const Text('Отправить тест сейчас'),
          ),
          const SizedBox(height: 24),
          DecoratedBox(
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.55),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.info_outline, size: 20, color: theme.colorScheme.primary),
                  const SizedBox(width: 10),
                  Expanded(child: Text(status)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
