import 'package:cloud_firestore/cloud_firestore.dart';

class SystemSummary {
  final bool runActive;
  final String railState;
  final int loadedConfigVersion;
  final String applyStatus;
  final num lastArrivedCm;
  final bool bleConnected;
  final Timestamp? updatedAt;
  final Timestamp? lastRunAt;

  const SystemSummary({
    this.runActive = false,
    this.railState = 'idle',
    this.loadedConfigVersion = 0,
    this.applyStatus = 'synced',
    this.lastArrivedCm = 0,
    this.bleConnected = false,
    this.updatedAt,
    this.lastRunAt,
  });

  factory SystemSummary.fromMap(Map<String, dynamic>? map) {
    final m = map ?? const <String, dynamic>{};
    return SystemSummary(
      runActive: m['run_active'] == true,
      railState: (m['rail_state'] ?? 'idle').toString(),
      loadedConfigVersion: (m['loaded_config_version'] as num?)?.toInt() ?? 0,
      applyStatus: (m['apply_status'] ?? 'synced').toString(),
      lastArrivedCm: (m['last_arrived_cm'] as num?) ?? 0,
      bleConnected: m['ble_connected'] == true,
      updatedAt: m['updated_at'] as Timestamp?,
      lastRunAt: m['last_run_at'] as Timestamp?,
    );
  }
}
