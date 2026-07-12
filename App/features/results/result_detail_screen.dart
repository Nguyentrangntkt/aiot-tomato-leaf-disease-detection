import 'package:flutter/material.dart';

import '../../models/scan_result.dart';

class ResultDetailScreen extends StatelessWidget {
  const ResultDetailScreen({super.key, required this.result});

  final ScanResult result;

  String _formatDate() {
    final dt = result.capturedAt?.toDate();
    return dt == null ? '—' : dt.toLocal().toString();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Chi tiết kết quả')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: AspectRatio(
              aspectRatio: 1,
              child: result.secureUrl.isEmpty
                  ? const ColoredBox(
                      color: Color(0x11000000),
                      child: Center(child: Icon(Icons.image_not_supported_outlined, size: 56)),
                    )
                  : Image.network(
                      result.secureUrl,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => const ColoredBox(
                        color: Color(0x11000000),
                        child: Center(child: Icon(Icons.broken_image_outlined, size: 56)),
                      ),
                    ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Nhãn bệnh: ${result.diseaseLabel}', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 10),
                  Text('Độ tin cậy: ${result.confidencePercent}'),
                  const SizedBox(height: 6),
                  Text('Vị trí: ${result.positionCm} cm'),
                  const SizedBox(height: 6),
                  Text('Run ID: ${result.runId.isEmpty ? '—' : result.runId}'),
                  const SizedBox(height: 6),
                  Text('Thời gian chụp: ${_formatDate()}'),
                  const SizedBox(height: 6),
                  Text('public_id: ${result.publicId.isEmpty ? '—' : result.publicId}'),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
