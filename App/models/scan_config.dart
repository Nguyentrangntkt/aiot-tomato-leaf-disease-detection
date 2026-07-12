class ScanConfig {
  final int numScans;
  final int intervalMinutes;

  /// Authoritative rail stop positions in centimeters.
  final List<int> positions;

  /// Optional metadata used by the UI.
  final int? plantCount;
  final int? spacingCm;

  ScanConfig({
    required this.numScans,
    required this.intervalMinutes,
    required this.positions,
    this.plantCount,
    this.spacingCm,
  });

  Map<String, dynamic> toMap() => {
        'num_scans': numScans,
        'interval_minutes': intervalMinutes,
        'positions': positions,
        if (plantCount != null) 'plant_count': plantCount,
        if (spacingCm != null) 'spacing_cm': spacingCm,
      };
}
