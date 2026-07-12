import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/material.dart';

import '../../data/auth/auth_service.dart';
import '../../data/firestore/firestore_service.dart';
import '../../models/scan_result.dart';
import 'result_detail_screen.dart';

class ResultScreen extends StatelessWidget {
  const ResultScreen({super.key});

  String _formatDate(Timestamp? ts) {
    final dt = ts?.toDate();
    return dt == null ? '—' : dt.toLocal().toString();
  }

  @override
  Widget build(BuildContext context) {
    final service = FirestoreService();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Log quét'),
        actions: [
          IconButton(
            tooltip: 'Đăng xuất',
            onPressed: () => AuthService().signOut(),
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
        stream: service.scanResultsStream(limit: 100),
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(child: Text('Firestore lỗi: ${snapshot.error}'));
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }

          final docs = snapshot.data!.docs;
          if (docs.isEmpty) {
            return const Center(child: Text('Chưa phát hiện lá bệnh nào'));
          }

          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: docs.length,
            separatorBuilder: (_, __) => const SizedBox(height: 12),
            itemBuilder: (context, index) {
              final result = ScanResult.fromDoc(docs[index]);

              return Card(
                clipBehavior: Clip.antiAlias,
                child: InkWell(
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(builder: (_) => ResultDetailScreen(result: result)),
                    );
                  },
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        ClipRRect(
                          borderRadius: BorderRadius.circular(12),
                          child: SizedBox(
                            width: 92,
                            height: 92,
                            child: result.secureUrl.isEmpty
                                ? const ColoredBox(
                                    color: Color(0x11000000),
                                    child: Icon(Icons.image_not_supported_outlined),
                                  )
                                : Image.network(
                                    result.secureUrl,
                                    fit: BoxFit.cover,
                                    errorBuilder: (_, __, ___) => const ColoredBox(
                                      color: Color(0x11000000),
                                      child: Icon(Icons.broken_image_outlined),
                                    ),
                                  ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                result.diseaseLabel,
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                              const SizedBox(height: 6),
                              Text('Độ tin cậy: ${result.confidencePercent}'),
                              const SizedBox(height: 4),
                              Text('Vị trí: ${result.positionCm} cm'),
                              const SizedBox(height: 4),
                              Text('Run ID: ${result.runId.isEmpty ? '—' : result.runId}'),
                              const SizedBox(height: 4),
                              Text(
                                'Thời gian: ${_formatDate(result.capturedAt)}',
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 8),
                        const Icon(Icons.chevron_right),
                      ],
                    ),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}
