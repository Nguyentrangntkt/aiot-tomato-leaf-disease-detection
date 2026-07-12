class UserProfile {
  final String role;
  final bool active;
  final String name;
  final String email;

  const UserProfile({
    required this.role,
    required this.active,
    required this.name,
    required this.email,
  });

  bool get isManager => active && role == 'manager';

  factory UserProfile.fromMap(Map<String, dynamic>? map) {
    final m = map ?? const <String, dynamic>{};
    return UserProfile(
      role: (m['role'] ?? '').toString(),
      active: m['active'] == true,
      name: (m['name'] ?? '').toString(),
      email: (m['email'] ?? '').toString(),
    );
  }
}
