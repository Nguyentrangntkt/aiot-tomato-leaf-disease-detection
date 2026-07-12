import 'dart:async';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../data/firestore/firestore_service.dart';
import '../../models/scan_config.dart';

class ScanConfigScreen extends StatefulWidget {
  const ScanConfigScreen({super.key});

  @override
  State<ScanConfigScreen> createState() => _ScanConfigScreenState();
}

class _ScanConfigScreenState extends State<ScanConfigScreen> {
  final _service = FirestoreService();

  static const int _maxLengthCm = 81;
  static const int _offsetCm = 4;
  static const int _maxPlantCount = _maxLengthCm - _offsetCm + 1;

  final _formKey = GlobalKey<FormState>();
  final _scansController = TextEditingController(text: '2');
  final _intervalController = TextEditingController(text: '1');
  final _plantCountController = TextEditingController(text: '3');
  final _spacingController = TextEditingController(text: '20');

  final _focusScans = FocusNode();
  final _focusInterval = FocusNode();
  final _focusPlant = FocusNode();
  final _focusSpacing = FocusNode();

  String _selectedPolicy = 'after_route';
  List<int> _positions = const [4, 24, 44];
  String _positionsHint = '';
  int _currentVersion = 0;
  Timestamp? _updatedAt;
  bool _saving = false;
  StreamSubscription<DocumentSnapshot<Map<String, dynamic>>>? _cfgSub;

  int? _loadedPlantCount;
  int? _loadedSpacingCm;
  List<int> _loadedPositions = const [];

  bool get _isEditing =>
      _focusScans.hasFocus ||
          _focusInterval.hasFocus ||
          _focusPlant.hasFocus ||
          _focusSpacing.hasFocus;

  bool get _positionEditingAllowed => _selectedPolicy == 'manual_restart';

  @override
  void initState() {
    super.initState();
    _rebuildPositions();
    _plantCountController.addListener(_rebuildPositions);
    _spacingController.addListener(_rebuildPositions);

    _cfgSub = _service.currentConfigStream().listen((doc) {
      final data = doc.data();
      if (data == null) return;
      if (_isEditing) return;

      final numScans = data['num_scans'];
      final intervalMinutes = data['interval_minutes'];
      final plantCount = data['plant_count'];
      final spacingCm = data['spacing_cm'];
      final positions = data['positions'];

      if (numScans != null) _scansController.text = numScans.toString();
      if (intervalMinutes != null) {
        _intervalController.text = intervalMinutes.toString();
      }
      if (plantCount != null) _plantCountController.text = plantCount.toString();
      if (spacingCm != null) _spacingController.text = spacingCm.toString();

      _selectedPolicy = (data['apply_policy'] ?? 'after_route').toString();
      _currentVersion = (data['version'] as num?)?.toInt() ?? 0;
      _updatedAt = data['updated_at'] as Timestamp?;

      _loadedPlantCount = (plantCount is num) ? plantCount.toInt() : null;
      _loadedSpacingCm = (spacingCm is num) ? spacingCm.toInt() : null;
      _loadedPositions = positions is List
          ? positions
              .whereType<num>()
              .map((e) => e.toInt())
              .toList()
          : const [];

      if (plantCount == null || spacingCm == null) {
        if (_loadedPositions.isNotEmpty) {
          _positions = List<int>.from(_loadedPositions);
          _positionsHint = 'Đã nạp ${_positions.length} vị trí từ Firebase.';
        } else {
          _positions = const [];
          _positionsHint = 'Chưa có vị trí dừng.';
        }
      } else {
        _rebuildPositions();
      }

      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _cfgSub?.cancel();
    _scansController.dispose();
    _intervalController.dispose();
    _plantCountController.dispose();
    _spacingController.dispose();
    _focusScans.dispose();
    _focusInterval.dispose();
    _focusPlant.dispose();
    _focusSpacing.dispose();
    super.dispose();
  }

  String _formatDate(Timestamp? ts) {
    final dt = ts?.toDate();
    return dt == null ? '—' : dt.toLocal().toString();
  }

  String _policyLabel(String policy) {
    switch (policy) {
      case 'manual_restart':
        return 'Dừng rồi chạy lại';
      case 'after_route':
      default:
        return 'Sau khi hoàn thành lượt hiện tại';
    }
  }

  bool _positionsWithinRail(List<int> positions) {
    return positions.isNotEmpty && positions.every((pos) => pos > 0 && pos <= _maxLengthCm);
  }

  void _rebuildPositions() {
    final plantCount = int.tryParse(_plantCountController.text.trim());
    final spacing = int.tryParse(_spacingController.text.trim());

    if (plantCount == null ||
        spacing == null ||
        plantCount <= 0 ||
        spacing <= 0 ||
        spacing > _maxLengthCm) {
      if (mounted) {
        setState(() {
          _positions = const [];
          _positionsHint = 'Nhập số cây và khoảng cách hợp lệ để tạo vị trí dừng.';
        });
      }
      return;
    }

    final positions = <int>[];
    for (int i = 0; i < plantCount; i++) {
      final pos = _offsetCm + i * spacing;
      if (pos > _maxLengthCm) break;
      positions.add(pos);
    }

    String hint;
    if (positions.isEmpty) {
      hint = 'Không tạo được vị trí nào. Hãy kiểm tra lại dữ liệu nhập.';
    } else if (positions.length < plantCount) {
      hint =
      'Ray $_maxLengthCm cm chỉ đủ ${positions.length}/$plantCount vị trí. Hãy giảm số cây hoặc khoảng cách.';
    } else {
      hint = 'Tạo ${positions.length} vị trí dừng từ ${positions.first} đến ${positions.last} cm.';
    }

    if (mounted) {
      setState(() {
        _positions = positions;
        _positionsHint = hint;
      });
    }
  }

  Future<void> _saveConfig() async {
    if (!_formKey.currentState!.validate()) return;

    List<int> positionsToSave;
    int? plantCountToSave;
    int? spacingToSave;

    if (_positionEditingAllowed) {
      _rebuildPositions();

      if (_positions.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Danh sách vị trí rỗng. Vui lòng kiểm tra số cây và khoảng cách.'),
          ),
        );
        return;
      }

      final requestedPlantCount = int.parse(_plantCountController.text.trim());
      if (_positions.length < requestedPlantCount) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Cấu hình vượt quá ray 81 cm. Vui lòng giảm số cây hoặc khoảng cách.'),
          ),
        );
        return;
      }

      positionsToSave = List<int>.from(_positions);
      plantCountToSave = int.tryParse(_plantCountController.text.trim());
      spacingToSave = int.tryParse(_spacingController.text.trim());
    } else {
      positionsToSave = List<int>.from(_loadedPositions.isNotEmpty ? _loadedPositions : _positions);
      plantCountToSave = _loadedPlantCount ?? int.tryParse(_plantCountController.text.trim());
      spacingToSave = _loadedSpacingCm ?? int.tryParse(_spacingController.text.trim());

      if (positionsToSave.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Chưa có vị trí dừng hiện tại để giữ nguyên. Hãy chọn “Dừng rồi chạy lại” để cấu hình lại vị trí.'),
          ),
        );
        return;
      }
    }

    if (!_positionsWithinRail(positionsToSave)) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Vị trí phải nằm trong ray 1-$_maxLengthCm cm.')),
      );
      return;
    }

    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;

    final cfg = ScanConfig(
      numScans: int.parse(_scansController.text.trim()),
      intervalMinutes: int.parse(_intervalController.text.trim()),
      positions: positionsToSave,
      plantCount: plantCountToSave,
      spacingCm: spacingToSave,
    );

    setState(() => _saving = true);
    try {
      await _service.saveSystemConfig(
        config: cfg,
        uid: user.uid,
        nextVersion: _currentVersion + 1,
        applyPolicy: _selectedPolicy,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            _positionEditingAllowed
                ? 'Đã lưu cấu hình hệ thống.'
                : 'Đã lưu cấu hình. Vị trí dừng hiện tại được giữ nguyên và sẽ áp dụng sau khi hết lượt.',
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Lưu cấu hình thất bại: $e')),
      );
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Widget _infoTile({required IconData icon, required String label, required String value}) {
    return Row(
      children: [
        Icon(icon, size: 18),
        const SizedBox(width: 8),
        Expanded(child: Text(label)),
        const SizedBox(width: 12),
        Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
      ],
    );
  }

  Widget _sectionCard({required BuildContext context, required Widget child}) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: child,
      ),
    );
  }

  Widget _buildPolicyNotice(ColorScheme cs, TextTheme tt) {
    final isAfterRoute = !_positionEditingAllowed;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: isAfterRoute
            ? cs.secondaryContainer.withOpacity(0.45)
            : cs.primaryContainer.withOpacity(0.45),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: isAfterRoute ? cs.secondary : cs.primary,
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            isAfterRoute ? Icons.info_outline : Icons.settings_backup_restore_outlined,
            color: isAfterRoute ? cs.secondary : cs.primary,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              isAfterRoute
                  ? 'Bạn đang chọn “Sau khi hoàn thành lượt hiện tại”. Chỉ nên chỉnh số lượt quét và thời gian nghỉ. Phần số cây và khoảng cách được giữ nguyên để tránh đổi vị trí dừng giữa chừng.'
                  : 'Bạn đang chọn “Dừng rồi chạy lại”. Có thể chỉnh cả số cây, khoảng cách và danh sách vị trí dừng. Cấu hình mới sẽ áp dụng khi dừng hệ thống và bấm chạy lại.',
              style: tt.bodyMedium?.copyWith(color: cs.onSurface),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(title: const Text('Cài đặt hệ thống')),
      body: SafeArea(
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _sectionCard(
                  context: context,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Thiết lập quét cho hệ thống ray 81 cm', style: tt.titleLarge),
                      const SizedBox(height: 8),
                      Text(
                        'Chọn chính sách áp dụng trước, sau đó cấu hình các thông số phù hợp với cách hệ thống sẽ nhận thay đổi.',
                        style: tt.bodyMedium?.copyWith(color: cs.onSurfaceVariant),
                      ),
                      const SizedBox(height: 16),
                      _infoTile(
                        icon: Icons.numbers_outlined,
                        label: 'Version cấu hình',
                        value: _currentVersion.toString(),
                      ),
                      const SizedBox(height: 10),
                      _infoTile(
                        icon: Icons.update_outlined,
                        label: 'Cập nhật gần nhất',
                        value: _formatDate(_updatedAt),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                _sectionCard(
                  context: context,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Chính sách áp dụng', style: tt.titleMedium),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        value: _selectedPolicy,
                        decoration: const InputDecoration(
                          labelText: 'Chính sách áp dụng',
                          prefixIcon: Icon(Icons.rule_folder_outlined),
                        ),
                        items: const [
                          DropdownMenuItem(
                            value: 'after_route',
                            child: Text('Sau khi hoàn thành lượt hiện tại'),
                          ),
                          DropdownMenuItem(
                            value: 'manual_restart',
                            child: Text('Dừng rồi chạy lại'),
                          ),
                        ],
                        onChanged: (value) {
                          if (value == null) return;
                          setState(() => _selectedPolicy = value);
                        },
                      ),
                      const SizedBox(height: 12),
                      _buildPolicyNotice(cs, tt),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                _sectionCard(
                  context: context,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Cấu hình quét', style: tt.titleMedium),
                      const SizedBox(height: 12),
                      TextFormField(
                        focusNode: _focusScans,
                        controller: _scansController,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: 'Số lượt quét',
                          prefixIcon: Icon(Icons.repeat_outlined),
                        ),
                        validator: (v) {
                          final n = int.tryParse((v ?? '').trim());
                          if (n == null) return 'Vui lòng nhập số';
                          if (n <= 0) return 'Phải > 0';
                          return null;
                        },
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        focusNode: _focusInterval,
                        controller: _intervalController,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: 'Khoảng nghỉ giữa lượt (phút)',
                          prefixIcon: Icon(Icons.schedule_outlined),
                        ),
                        validator: (v) {
                          final n = int.tryParse((v ?? '').trim());
                          if (n == null) return 'Vui lòng nhập số';
                          if (n < 0) return 'Phải >= 0';
                          return null;
                        },
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                _sectionCard(
                  context: context,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text('Cấu hình vị trí dừng', style: tt.titleMedium),
                          ),
                          if (!_positionEditingAllowed)
                            Chip(
                              avatar: const Icon(Icons.lock_outline, size: 18),
                              label: const Text('Đang khóa'),
                              visualDensity: VisualDensity.compact,
                            ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      AbsorbPointer(
                        absorbing: !_positionEditingAllowed,
                        child: Opacity(
                          opacity: _positionEditingAllowed ? 1 : 0.55,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: TextFormField(
                                      focusNode: _focusPlant,
                                      controller: _plantCountController,
                                      enabled: _positionEditingAllowed,
                                      keyboardType: TextInputType.number,
                                      decoration: const InputDecoration(
                                        labelText: 'Số cây',
                                        prefixIcon: Icon(Icons.filter_vintage_outlined),
                                      ),
                                      validator: (v) {
                                        final n = int.tryParse((v ?? '').trim());
                                        if (n == null) return 'Nhập số';
                                        if (n <= 0) return '> 0';
                                        if (n > _maxPlantCount) return 'Tối đa $_maxPlantCount cây';
                                        return null;
                                      },
                                    ),
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: TextFormField(
                                      focusNode: _focusSpacing,
                                      controller: _spacingController,
                                      enabled: _positionEditingAllowed,
                                      keyboardType: TextInputType.number,
                                      decoration: const InputDecoration(
                                        labelText: 'Khoảng cách (cm)',
                                        prefixIcon: Icon(Icons.straighten_outlined),
                                      ),
                                      validator: (v) {
                                        final n = int.tryParse((v ?? '').trim());
                                        if (n == null) return 'Nhập số';
                                        if (n <= 0) return '> 0';
                                        if (n > _maxLengthCm) return 'Tối đa $_maxLengthCm cm';
                                        return null;
                                      },
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 14),
                              Container(
                                width: double.infinity,
                                padding: const EdgeInsets.all(14),
                                decoration: BoxDecoration(
                                  color: cs.surfaceContainerHighest.withOpacity(0.55),
                                  borderRadius: BorderRadius.circular(16),
                                  border: Border.all(color: cs.outlineVariant),
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      children: [
                                        Icon(Icons.route_outlined, color: cs.primary),
                                        const SizedBox(width: 8),
                                        Text('Vị trí tính được', style: tt.titleSmall),
                                      ],
                                    ),
                                    const SizedBox(height: 10),
                                    if (_positions.isEmpty)
                                      Text('Chưa có vị trí hợp lệ.', style: tt.bodyMedium)
                                    else
                                      Wrap(
                                        spacing: 8,
                                        runSpacing: 8,
                                        children: [
                                          for (int i = 0; i < _positions.length; i++)
                                            Chip(
                                              avatar: CircleAvatar(
                                                backgroundColor: cs.primaryContainer,
                                                foregroundColor: cs.onPrimaryContainer,
                                                child: Text('${i + 1}'),
                                              ),
                                              label: Text('${_positions[i]} cm'),
                                            ),
                                        ],
                                      ),
                                    const SizedBox(height: 10),
                                    Text(
                                      _positionEditingAllowed
                                          ? _positionsHint
                                          : 'Phần vị trí dừng đang được giữ nguyên theo cấu hình hiện tại.',
                                      style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
                                    ),
                                    const SizedBox(height: 8),
                                    Text(
                                      'Quy ước hiện tại: ray dài 81 cm, điểm đầu tiên bắt đầu từ +$_offsetCm cm để tránh đè cảm biến.',
                                      style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      if (!_positionEditingAllowed) ...[
                        const SizedBox(height: 12),
                        Text(
                          'Muốn đổi số cây hoặc khoảng cách, hãy chuyển sang “Dừng rồi chạy lại”.',
                          style: tt.bodySmall?.copyWith(
                            color: cs.onSurfaceVariant,
                            fontStyle: FontStyle.italic,
                          ),
                        ),
                      ],
                      const SizedBox(height: 18),
                      FilledButton.icon(
                        onPressed: _saving ? null : _saveConfig,
                        icon: _saving
                            ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                            : const Icon(Icons.save_outlined),
                        label: Text(_saving ? 'Đang lưu...' : 'Lưu cấu hình'),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                _sectionCard(
                  context: context,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Giải thích', style: tt.titleMedium),
                      const SizedBox(height: 12),
                      Text('Chính sách áp dụng', style: tt.titleSmall),
                      const SizedBox(height: 8),
                      Text(
                        '• ${_policyLabel('after_route')}: cấu hình mới áp dụng sau khi hệ hoàn thành lượt quét hiện tại. Chỉ nên đổi số lượt quét và thời gian nghỉ.',
                      ),
                      const SizedBox(height: 6),
                      Text(
                        '• ${_policyLabel('manual_restart')}: cấu hình mới áp dụng khi bạn dừng hệ thống và bấm chạy lại. Có thể thay đổi cả vị trí dừng.',
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
