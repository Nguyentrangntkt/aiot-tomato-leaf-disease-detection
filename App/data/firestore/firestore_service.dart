import 'package:cloud_firestore/cloud_firestore.dart';

import '../../models/scan_config.dart';
import 'firestore_paths.dart';

class FirestoreService {
  FirestoreService({FirebaseFirestore? db}) : _db = db ?? FirebaseFirestore.instance;
  final FirebaseFirestore _db;
  // Trường tương thích cũ; hệ thống hiện chỉ dùng chế độ quét một chiều.
  static const String _scanMode = 'shuttle';

  Stream<DocumentSnapshot<Map<String, dynamic>>> currentConfigStream() {
    return _db
        .collection(FirestorePaths.systemConfigCol)
        .doc(FirestorePaths.currentConfigDoc)
        .snapshots();
  }

  Stream<DocumentSnapshot<Map<String, dynamic>>> systemStatusStream() {
    return _db
        .collection(FirestorePaths.systemStatusCol)
        .doc(FirestorePaths.systemStatusDoc)
        .snapshots();
  }

  Future<void> saveSystemConfig({
    required ScanConfig config,
    required String uid,
    required int nextVersion,
    String applyPolicy = 'after_route',
  }) async {
    await _db.collection(FirestorePaths.systemConfigCol).doc(FirestorePaths.currentConfigDoc).set({
      'version': nextVersion,
      'mode': _scanMode,
      'num_scans': config.numScans,
      'interval_minutes': config.intervalMinutes,
      'positions': config.positions,
      if (config.plantCount != null) 'plant_count': config.plantCount,
      if (config.spacingCm != null) 'spacing_cm': config.spacingCm,
      'apply_policy': applyPolicy,
      'updated_at': FieldValue.serverTimestamp(),
      'updated_by': uid,
    }, SetOptions(merge: true));
  }

  Stream<QuerySnapshot<Map<String, dynamic>>> scanResultsStream({int limit = 100}) {
    return _db
        .collection(FirestorePaths.scanResultsCol)
        .orderBy('captured_at', descending: true)
        .limit(limit)
        .snapshots();
  }
}
