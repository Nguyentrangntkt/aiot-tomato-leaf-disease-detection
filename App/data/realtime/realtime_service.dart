import 'package:firebase_database/firebase_database.dart';

import '../../models/live_status.dart';

class RealtimeService {
  RealtimeService({FirebaseDatabase? db}) : _db = db ?? FirebaseDatabase.instance;
  final FirebaseDatabase _db;

  DatabaseReference get _root => _db.ref();

  Stream<LiveStatus> liveStatusStream() {
    return _root.child('live').onValue.map((event) {
      final raw = event.snapshot.value;
      final map = (raw is Map) ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
      return LiveStatus.fromMap(map);
    });
  }

  Stream<ControlState> controlStateStream() {
    return _root.child('control').onValue.map((event) {
      final raw = event.snapshot.value;
      final map = (raw is Map) ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
      return ControlState.fromMap(map);
    });
  }

  Future<void> sendControl({
    bool stopRequested = false,
    bool pauseRequested = false,
    bool manualNextRequested = false,
    bool runRequested = false,
    required String updatedBy,
    required int requestId,
  }) {
    return _root.child('control').update({
      'stop_requested': stopRequested,
      'pause_requested': pauseRequested,
      'manual_next_requested': manualNextRequested,
      'run_requested': runRequested,
      'request_id': requestId,
      'updated_at': ServerValue.timestamp,
      'updated_by': updatedBy,
    });
  }
}
