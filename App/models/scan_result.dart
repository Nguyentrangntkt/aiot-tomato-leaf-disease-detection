import 'package:cloud_firestore/cloud_firestore.dart';

class ScanResult {
  final String id;
  final String secureUrl;
  final String publicId;
  final num positionCm;
  final Timestamp? capturedAt;
  final String runId;
  final String disease;
  final double confidence;

  const ScanResult({
    required this.id,
    required this.secureUrl,
    required this.publicId,
    required this.positionCm,
    required this.capturedAt,
    required this.runId,
    required this.disease,
    required this.confidence,
  });

  factory ScanResult.fromDoc(DocumentSnapshot<Map<String, dynamic>> doc) {
    final map = doc.data() ?? const <String, dynamic>{};
    return ScanResult(
      id: doc.id,
      secureUrl: (map['secure_url'] ?? '').toString(),
      publicId: (map['public_id'] ?? '').toString(),
      positionCm: (map['position_cm'] as num?) ?? 0,
      capturedAt: map['captured_at'] as Timestamp?,
      runId: (map['run_id'] ?? '').toString(),
      disease: (map['disease'] ?? '').toString(),
      confidence: (map['confidence'] is num)
          ? (map['confidence'] as num).toDouble()
          : 0.0,
    );
  }

  String get diseaseLabel {
    final v = disease.trim().toLowerCase().replaceAll(' ', '_').replaceAll('-', '_');
    switch (v) {
      case 'leafminer':
      case 'leaf_miner':
        return 'LeafMiner';
      case 'earlyblight':
      case 'early_blight':
        return 'EarlyBlight';
      case 'diseased':
      case 'diseased_?':
      case 'diseased_unknown':
        return 'Diseased (?)';
      case 'healthy':
        return 'Healthy';
      case 'uncertain':
        return 'Uncertain';
      case 'unknown':
        return 'Unknown';
      default:
        return disease.isEmpty ? '—' : disease;
    }
  }

  String get confidencePercent => '${(confidence * 100).toStringAsFixed(1)}%';
}
