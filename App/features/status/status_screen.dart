import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../data/auth/auth_service.dart';
import '../../data/firestore/firestore_service.dart';
import '../../data/realtime/realtime_service.dart';
import '../../models/live_status.dart';
import '../../models/system_summary.dart';
import '../config/scan_config_screen.dart';

class StatusScreen extends StatefulWidget {
  const StatusScreen({super.key});

  @override
  State<StatusScreen> createState() => _StatusScreenState();
}

class _StatusScreenState extends State<StatusScreen> {
  final _firestore = FirestoreService();
  final _realtime = RealtimeService();
  bool _sending = false;

  String _railStateLabel(String value) {
    switch (value) {
      case 'moving':
        return 'Đang di chuyển';
      case 'waiting_next':
        return 'Đang dừng để chụp';
      case 'interval_wait':
        return 'Đang nghỉ giữa lượt';
      case 'paused':
        return 'Tạm dừng';
      case 'completed':
        return 'Hoàn thành';
      case 'stopped':
        return 'Đã hủy lượt chạy';
      case 'error':
        return 'Lỗi';
      case 'idle':
      default:
        return 'Sẵn sàng';
    }
  }

  String _applyStatusLabel(String value) {
    switch (value) {
      case 'updating':
        return 'Đang cập nhật';
      case 'waiting_after_route':
        return 'Chờ hết lượt';
      case 'waiting_manual_restart':
        return 'Chờ dừng và chạy lại';
      case 'error':
        return 'Lỗi cấu hình';
      case 'synced':
      default:
        return 'Đồng bộ';
    }
  }

  String _diseaseLabel(String raw) {
    final v = raw.trim().toLowerCase().replaceAll(' ', '_').replaceAll('-', '_');
    switch (v) {
      case 'healthy':
        return 'Healthy';
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
      case 'uncertain':
        return 'Uncertain';
      case 'unknown':
        return 'Unknown';
      default:
        return raw.isEmpty ? '—' : raw;
    }
  }

  String _formatTimestamp(Timestamp? ts) {
    final dt = ts?.toDate();
    return dt == null ? '—' : dt.toLocal().toString();
  }

  String _formatMillis(num value) {
    if (value <= 0) return '—';
    return DateTime.fromMillisecondsSinceEpoch(value.toInt()).toLocal().toString();
  }

  String _formatCm(num value) => '${value.toStringAsFixed(1)} cm';

  bool _canPause(LiveStatus live) {
    return live.railState == 'moving' ||
        live.railState == 'waiting_next' ||
        live.railState == 'interval_wait';
  }

  bool _canRun(LiveStatus live, bool runActive) {
    return !runActive &&
        live.railState != 'moving' &&
        live.railState != 'waiting_next' &&
        live.railState != 'interval_wait' &&
        live.railState != 'paused';
  }

  bool _canResume(LiveStatus live) {
    return live.railState == 'paused';
  }

  bool _canStop(LiveStatus live, bool runActive) {
    return runActive ||
        live.railState == 'moving' ||
        live.railState == 'waiting_next' ||
        live.railState == 'interval_wait' ||
        live.railState == 'paused';
  }

  Future<void> _sendControl({
    bool stop = false,
    bool pause = false,
    bool run = false,
    String? commandLabel,
  }) async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;

    setState(() => _sending = true);
    try {
      await _realtime.sendControl(
        stopRequested: stop,
        pauseRequested: pause,
        manualNextRequested: false,
        runRequested: run,
        updatedBy: user.uid,
        requestId: DateTime.now().millisecondsSinceEpoch,
      );
      if (!mounted) return;
      final label = commandLabel ??
          (stop
              ? 'STOP'
              : pause
                  ? 'PAUSE'
                  : run
                      ? 'RUN'
                      : 'RUN');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Đã gửi lệnh $label.')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Gửi lệnh thất bại: $e')),
      );
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _confirmStop() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Hủy lượt chạy?'),
          content: const Text(
            'Stop sẽ hủy lượt quét hiện tại. Khi bấm Run lại, hệ thống sẽ chạy lại từ đầu route.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Không'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Stop'),
            ),
          ],
        );
      },
    );
    if (ok == true) {
      await _sendControl(stop: true);
    }
  }

  Widget _line(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Expanded(child: Text(label)),
          const SizedBox(width: 12),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }

  Widget _monitorCard(
    BuildContext context,
    SystemSummary summary,
    LiveStatus live,
    int firebaseVersion,
  ) {
    final tt = Theme.of(context).textTheme;
    final cs = Theme.of(context).colorScheme;
    final runActive = live.runActive || summary.runActive;
    final railState = live.railState.isEmpty ? summary.railState : live.railState;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.monitor_heart_outlined, color: cs.primary),
                const SizedBox(width: 8),
                Text('Giám sát hệ thống', style: tt.titleMedium),
                const Spacer(),
                Chip(label: Text(runActive ? 'Đang chạy' : 'Đang nghỉ')),
              ],
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                Chip(
                  avatar: Icon(
                    Icons.bluetooth_connected_outlined,
                    color: (live.bleConnected || summary.bleConnected)
                        ? Colors.green
                        : Theme.of(context).colorScheme.error,
                    size: 18,
                  ),
                  label: Text((live.bleConnected || summary.bleConnected) ? 'BLE kết nối' : 'BLE mất kết nối'),
                ),
                Chip(label: Text(_railStateLabel(railState))),
                Chip(label: Text(_applyStatusLabel(summary.applyStatus))),
              ],
            ),
            const SizedBox(height: 14),
            _line('Version trên Firebase', firebaseVersion.toString()),
            _line('Version thiết bị đã nạp', summary.loadedConfigVersion.toString()),
            _line('Vị trí hiện tại', _formatCm(live.currentPositionCm)),
            _line('Vị trí mục tiêu', _formatCm(live.targetPositionCm)),
            _line('Điểm vừa tới', _formatCm(live.lastArrivedCm != 0 ? live.lastArrivedCm : summary.lastArrivedCm)),
            _line('Lần chạy gần nhất', _formatTimestamp(summary.lastRunAt)),
            _line('Cập nhật live', _formatMillis(live.updatedAt)),
            _line('Cập nhật Firestore', _formatTimestamp(summary.updatedAt)),
          ],
        ),
      ),
    );
  }

  Widget _lastScanCard(BuildContext context, LiveStatus live) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final status = live.lastScanStatus.trim().toLowerCase();
    final label = _diseaseLabel(live.lastScanLabel);

    IconData icon;
    Color iconColor;
    String title;
    String subtitle;

    switch (status) {
      case 'running':
        icon = Icons.camera_alt_outlined;
        iconColor = cs.primary;
        title = 'Đang chụp và phân loại';
        subtitle = 'Rail đang giữ tại vị trí ${_formatCm(live.lastScanPositionCm)}.';
        break;
      case 'healthy':
        icon = Icons.check_circle_outline;
        iconColor = Colors.green;
        title = 'Không phát hiện bệnh';
        subtitle = 'Kết quả Healthy không upload Cloudinary và không lưu vào scan_results.';
        break;
      case 'disease': // Tương thích dữ liệu cũ.
      case 'diseased':
        icon = Icons.warning_amber_outlined;
        iconColor = cs.error;
        title = 'Đã phát hiện bệnh: $label';
        subtitle = 'Ảnh bệnh được lưu trong màn Log quét.';
        break;
      case 'uncertain':
        icon = Icons.help_outline;
        iconColor = Colors.orange;
        title = 'Kết quả chưa chắc chắn';
        subtitle = 'Uncertain không upload Cloudinary và không lưu kết quả chính thức.';
        break;
      case 'error':
        icon = Icons.error_outline;
        iconColor = cs.error;
        title = 'Lỗi phân loại';
        subtitle = live.lastScanNote.isEmpty ? 'Kiểm tra log trên Pi4.' : live.lastScanNote;
        break;
      case 'skipped':
        icon = Icons.info_outline;
        iconColor = cs.secondary;
        title = 'Lượt quét bị bỏ qua';
        subtitle = live.lastScanNote.isEmpty
            ? 'Lượt quét này không tạo kết quả phát hiện bệnh.'
            : live.lastScanNote;
        break;
      case 'idle':
      default:
        icon = Icons.eco_outlined;
        iconColor = cs.primary;
        title = 'Chưa có lượt phân loại mới';
        subtitle = 'Khi ESP32 báo ARRIVED, Pi4 sẽ tự capture và phân loại.';
        break;
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: iconColor),
                const SizedBox(width: 8),
                Text('Kết quả quét gần nhất', style: tt.titleMedium),
              ],
            ),
            const SizedBox(height: 12),
            Text(title, style: tt.titleSmall),
            const SizedBox(height: 6),
            Text(subtitle, style: tt.bodyMedium?.copyWith(color: cs.onSurfaceVariant)),
            const SizedBox(height: 12),
            _line('Vị trí', _formatCm(live.lastScanPositionCm)),
            _line('Nhãn', label),
            _line('Độ tin cậy', '${(live.lastScanConfidence * 100).toStringAsFixed(1)}%'),
            _line('Thời gian', _formatMillis(live.lastScanAt)),
          ],
        ),
      ),
    );
  }

  Widget _controlCard(
    BuildContext context,
    SystemSummary summary,
    LiveStatus live,
    ControlState control,
  ) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final isPaused = live.railState == 'paused';
    final runActive = live.runActive || summary.runActive;
    final isBlocked = _sending || control.hasPendingRequest;
    final canRunOrResume = isPaused ? _canResume(live) : _canRun(live, runActive);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.gamepad_outlined, color: cs.primary),
                const SizedBox(width: 8),
                Text('Điều khiển', style: tt.titleMedium),
              ],
            ),
            const SizedBox(height: 10),
            Text(
              'Run bắt đầu lượt quét mới. Resume chạy tiếp khi hệ thống đang tạm dừng.',
              style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: isBlocked || !canRunOrResume
                        ? null
                        : () => _sendControl(
                              run: true,
                              commandLabel: isPaused ? 'RESUME' : 'RUN',
                            ),
                    icon: const Icon(Icons.play_arrow_rounded),
                    label: Text(isPaused ? 'Resume' : 'Run'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: isBlocked || !_canPause(live)
                        ? null
                        : () => _sendControl(pause: true),
                    icon: const Icon(Icons.pause_rounded),
                    label: const Text('Pause'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: cs.error),
              onPressed: isBlocked || !_canStop(live, runActive)
                  ? null
                  : _confirmStop,
              icon: const Icon(Icons.stop_rounded),
              label: const Text('Stop'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Giám sát'),
        actions: [
          IconButton(
            tooltip: 'Cài đặt',
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const ScanConfigScreen()),
              );
            },
            icon: const Icon(Icons.settings_outlined),
          ),
          IconButton(
            tooltip: 'Đăng xuất',
            onPressed: () => AuthService().signOut(),
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: StreamBuilder<DocumentSnapshot<Map<String, dynamic>>>(
        stream: _firestore.currentConfigStream(),
        builder: (context, configSnap) {
          final firebaseVersion = (configSnap.data?.data()?['version'] as num?)?.toInt() ?? 0;

          return StreamBuilder<DocumentSnapshot<Map<String, dynamic>>>(
            stream: _firestore.systemStatusStream(),
            builder: (context, statusSnap) {
              if (configSnap.hasError || statusSnap.hasError) {
                return Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      'Không đọc được trạng thái hệ thống. Hãy kiểm tra Firestore rules cho system_status/current.\n\nChi tiết: ${configSnap.error ?? statusSnap.error}',
                      textAlign: TextAlign.center,
                    ),
                  ),
                );
              }

              if ((configSnap.connectionState == ConnectionState.waiting && !configSnap.hasData) ||
                  (statusSnap.connectionState == ConnectionState.waiting && !statusSnap.hasData)) {
                return const Center(child: CircularProgressIndicator());
              }

              final summary = SystemSummary.fromMap(statusSnap.data?.data());

              return StreamBuilder<LiveStatus>(
                stream: _realtime.liveStatusStream(),
                builder: (context, liveSnap) {
                  final live = liveSnap.data ?? LiveStatus.empty();

                  return ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      _monitorCard(context, summary, live, firebaseVersion),
                      const SizedBox(height: 12),
                      _lastScanCard(context, live),
                      const SizedBox(height: 12),
                      StreamBuilder<ControlState>(
                        stream: _realtime.controlStateStream(),
                        builder: (context, controlSnap) {
                          final control =
                              controlSnap.data ?? ControlState.fromMap(const <String, dynamic>{});
                          return _controlCard(context, summary, live, control);
                        },
                      ),
                    ],
                  );
                },
              );
            },
          );
        },
      ),
    );
  }
}
