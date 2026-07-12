class LiveStatus {
  final String railState;
  final bool runActive;
  final num currentPositionCm;
  final num targetPositionCm;
  final num lastArrivedCm;
  final bool bleConnected;
  final num updatedAt;

  // Kết quả quét gần nhất. Healthy/Uncertain không lưu vào scan_results,
  // nên app đọc các field này để biết hệ vừa quét xong ở vị trí nào.
  final String lastScanStatus;
  final String lastScanLabel;
  final bool lastScanHasDisease;
  final num lastScanConfidence;
  final num lastScanPositionCm;
  final num lastScanAt;
  final String lastScanNote;

  LiveStatus({
    required this.railState,
    required this.runActive,
    required this.currentPositionCm,
    required this.targetPositionCm,
    required this.lastArrivedCm,
    required this.bleConnected,
    required this.updatedAt,
    required this.lastScanStatus,
    required this.lastScanLabel,
    required this.lastScanHasDisease,
    required this.lastScanConfidence,
    required this.lastScanPositionCm,
    required this.lastScanAt,
    required this.lastScanNote,
  });

  factory LiveStatus.empty() {
    return LiveStatus.fromMap(const <String, dynamic>{});
  }

  factory LiveStatus.fromMap(Map<String, dynamic> map) {
    return LiveStatus(
      railState: (map['rail_state'] ?? 'idle').toString(),
      runActive: map['run_active'] == true,
      currentPositionCm: (map['current_position_cm'] as num?) ?? 0,
      targetPositionCm: (map['target_position_cm'] as num?) ?? 0,
      lastArrivedCm: (map['last_arrived_cm'] as num?) ?? 0,
      bleConnected: map['ble_connected'] == true,
      updatedAt: (map['updated_at'] as num?) ?? 0,
      lastScanStatus: (map['last_scan_status'] ?? 'idle').toString(),
      lastScanLabel: (map['last_scan_label'] ?? '').toString(),
      lastScanHasDisease: map['last_scan_has_disease'] == true,
      lastScanConfidence: (map['last_scan_confidence'] as num?) ?? 0,
      lastScanPositionCm: (map['last_scan_position_cm'] as num?) ?? 0,
      lastScanAt: (map['last_scan_at'] as num?) ?? 0,
      lastScanNote: (map['last_scan_note'] ?? '').toString(),
    );
  }
}

class ControlState {
  final bool stopRequested;
  final bool pauseRequested;
  final bool manualNextRequested;
  final bool runRequested;
  final num requestId;
  final num updatedAt;
  final String updatedBy;

  ControlState({
    required this.stopRequested,
    required this.pauseRequested,
    required this.manualNextRequested,
    required this.runRequested,
    required this.requestId,
    required this.updatedAt,
    required this.updatedBy,
  });

  factory ControlState.fromMap(Map<String, dynamic> map) {
    return ControlState(
      stopRequested: map['stop_requested'] == true,
      pauseRequested: map['pause_requested'] == true,
      manualNextRequested: map['manual_next_requested'] == true,
      runRequested: map['run_requested'] == true,
      requestId: (map['request_id'] as num?) ?? 0,
      updatedAt: (map['updated_at'] as num?) ?? 0,
      updatedBy: (map['updated_by'] ?? '').toString(),
    );
  }

  bool get hasPendingRequest {
    return stopRequested || pauseRequested || manualNextRequested || runRequested;
  }
}
