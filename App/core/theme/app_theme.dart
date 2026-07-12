import 'package:flutter/material.dart';

class AppTheme {
  // Palette gợi ý: xanh nhà kính + đỏ cà chua
  static const _seedGreenhouse = Color(0xFF1B5E20);
  static const _tomato = Color(0xFFD32F2F);

  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(
      seedColor: _seedGreenhouse,
      brightness: Brightness.light,
    ).copyWith(
      primary: _seedGreenhouse,
      secondary: const Color(0xFF2E7D32),
      tertiary: const Color(0xFF00796B),
      error: _tomato,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
        elevation: 0,
      ),
      inputDecorationTheme: InputDecorationTheme(
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(14)),
      ),
      cardTheme: CardThemeData(
        elevation: 0.5,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
    );
  }

  static ThemeData dark() {
    final scheme = ColorScheme.fromSeed(
      seedColor: _seedGreenhouse,
      brightness: Brightness.dark,
    ).copyWith(
      primary: const Color(0xFF66BB6A),
      secondary: const Color(0xFF81C784),
      tertiary: const Color(0xFF4DB6AC),
      error: _tomato,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
        elevation: 0,
      ),
      inputDecorationTheme: InputDecorationTheme(
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(14)),
      ),
      cardTheme: CardThemeData(
        elevation: 0.5,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
    );
  }
}
