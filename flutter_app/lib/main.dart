import 'dart:async';
import 'dart:convert';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter_health_connect/flutter_health_connect.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:workmanager/workmanager.dart';

const String sleepTaskName = 'sleep_daily_sync';
const String sleepTaskUniqueName = 'sleep_daily_sync_unique';

const List<HealthConnectDataType> sleepTypes = [
  HealthConnectDataType.SleepSession,
  HealthConnectDataType.SleepStage,
];

@pragma('vm:entry-point')
void callbackDispatcher() {
  Workmanager().executeTask((task, inputData) async {
    DartPluginRegistrant.ensureInitialized();

    if (task != sleepTaskName) {
      return true;
    }

    final prefs = await SharedPreferences.getInstance();
    final backendUrl =
        inputData?['backendUrl'] as String? ?? prefs.getString('backendUrl') ?? '';
    final telegramId =
        inputData?['telegramId'] as String? ?? prefs.getString('telegramId') ?? '';
    final secret = inputData?['secret'] as String? ?? prefs.getString('secret') ?? '';

    if (backendUrl.isEmpty || telegramId.isEmpty) {
      return false;
    }

    try {
      final payload = await collectSleepPayload(telegramId);
      await sendSleepPayload(
        backendUrl: backendUrl,
        secret: secret,
        payload: payload,
      );
      return true;
    } catch (_) {
      return false;
    }
  });
}

Future<Map<String, dynamic>> collectSleepPayload(String telegramId) async {
  final now = DateTime.now();
  final startTime = now.subtract(const Duration(hours: 30));

  final records = await HealthConnectFactory.getRecord(
    types: sleepTypes,
    startTime: startTime,
    endTime: now,
  );

  final parsed = parseSleepRecords(records);

  return {
    'telegram_id': int.tryParse(telegramId) ?? telegramId,
    'date': now.toIso8601String(),
    'source': 'health_connect_flutter_apk',
    'total_sleep_minutes': parsed.totalSleepMinutes,
    'deep_sleep_minutes': parsed.deepSleepMinutes,
    'light_sleep_minutes': parsed.lightSleepMinutes,
    'rem_sleep_minutes': parsed.remSleepMinutes,
    'awake_minutes': parsed.awakeMinutes,
    'raw_debug': parsed.debug,
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
    required this.debug,
  });

  final int totalSleepMinutes;
  final int deepSleepMinutes;
  final int lightSleepMinutes;
  final int remSleepMinutes;
  final int awakeMinutes;
  final Map<String, dynamic> debug;
}

ParsedSleep parseSleepRecords(dynamic records) {
  var deep = 0;
  var light = 0;
  var rem = 0;
  var awake = 0;
  var sessionTotal = 0;

  void visit(dynamic value) {
    if (value is List) {
      for (final item in value) {
        visit(item);
      }
      return;
    }

    if (value is Map) {
      final map = value.map((key, item) => MapEntry(key.toString(), item));
      final typeText = map.values.join(' ').toLowerCase();
      final minutes = extractDurationMinutes(map);

      if (minutes > 0) {
        if (typeText.contains('deep')) {
          deep += minutes;
        } else if (typeText.contains('rem')) {
          rem += minutes;
        } else if (typeText.contains('light')) {
          light += minutes;
        } else if (typeText.contains('awake') ||
            typeText.contains('wake') ||
            typeText.contains('out_of_bed')) {
          awake += minutes;
        } else if (typeText.contains('sleep')) {
          sessionTotal += minutes;
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
    debug: {
      'stage_total': stageTotal,
      'session_total': sessionTotal,
    },
  );
}

int extractDurationMinutes(Map<String, dynamic> map) {
  final direct = firstValue(map, [
    'duration',
    'durationMinutes',
    'minutes',
    'value',
  ]);

  if (direct != null) {
    final parsed = int.tryParse(direct.toString());
    if (parsed != null && parsed > 0 && parsed < 24 * 60) {
      return parsed;
    }
  }

  final start = parseDate(firstValue(map, [
    'startTime',
    'start_time',
    'start',
    'from',
  ]));
  final end = parseDate(firstValue(map, [
    'endTime',
    'end_time',
    'end',
    'to',
  ]));

  if (start == null || end == null) {
    return 0;
  }

  final minutes = end.difference(start).inMinutes;
  if (minutes <= 0 || minutes > 24 * 60) {
    return 0;
  }
  return minutes;
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
      title: 'Somnus Sync',
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
  final backendController = TextEditingController();
  final telegramController = TextEditingController();
  final secretController = TextEditingController();
  String status = 'Не запущено';

  @override
  void initState() {
    super.initState();
    loadSaved();
  }

  @override
  void dispose() {
    backendController.dispose();
    telegramController.dispose();
    secretController.dispose();
    super.dispose();
  }

  Future<void> loadSaved() async {
    final prefs = await SharedPreferences.getInstance();
    backendController.text = prefs.getString('backendUrl') ?? '';
    telegramController.text = prefs.getString('telegramId') ?? '';
    secretController.text = prefs.getString('secret') ?? '';
  }

  Future<void> start() async {
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

    final backendUrl = backendController.text.trim();
    final telegramId = telegramController.text.trim();
    final secret = secretController.text.trim();

    if (backendUrl.isEmpty || telegramId.isEmpty) {
      setState(() => status = 'Заполни URL сервера и Telegram ID');
      return;
    }

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('backendUrl', backendUrl);
    await prefs.setString('telegramId', telegramId);
    await prefs.setString('secret', secret);

    await Workmanager().registerPeriodicTask(
      sleepTaskUniqueName,
      sleepTaskName,
      frequency: const Duration(hours: 24),
      initialDelay: const Duration(minutes: 15),
      constraints: Constraints(networkType: NetworkType.connected),
      inputData: {
        'backendUrl': backendUrl,
        'telegramId': telegramId,
        'secret': secret,
      },
      existingWorkPolicy: ExistingWorkPolicy.replace,
    );

    setState(() => status = 'Готово. Фоновая отправка включена');
  }

  Future<void> testNow() async {
    final backendUrl = backendController.text.trim();
    final telegramId = telegramController.text.trim();

    if (backendUrl.isEmpty || telegramId.isEmpty) {
      setState(() => status = 'Заполни URL сервера и Telegram ID');
      return;
    }

    setState(() => status = 'Отправляю тест...');

    final payload = await collectSleepPayload(telegramId);
    await sendSleepPayload(
      backendUrl: backendUrl,
      secret: secretController.text.trim(),
      payload: payload,
    );

    setState(() => status = 'Тест отправлен');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Somnus Sync')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: backendController,
            decoration: const InputDecoration(
              labelText: 'URL сервера',
              hintText: 'https://your-app.up.railway.app/webhook/sleep-apk',
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: telegramController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: 'Telegram ID'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: secretController,
            decoration: const InputDecoration(labelText: 'Webhook secret'),
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: start,
            child: const Text('Запустить и выдать разрешения'),
          ),
          const SizedBox(height: 12),
          OutlinedButton(
            onPressed: testNow,
            child: const Text('Отправить тест сейчас'),
          ),
          const SizedBox(height: 24),
          Text(status),
        ],
      ),
    );
  }
}
