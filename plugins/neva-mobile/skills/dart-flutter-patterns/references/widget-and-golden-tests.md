# Widget, Golden, and Integration Tests for Flutter

<!-- Written for Neva as an extension of the dart-flutter-patterns skill adapted from affaan-m/ECC (MIT), commit d3b8a3e. -->

Tests are the contract that lets you refactor a screen without opening the simulator. Write them in this order for any new screen: controller unit tests, one widget test per state, goldens in both directions, then extend the integration flow if the screen is on a critical path.

## 1. The shared harness

Every widget and golden test pumps through one `TestApp`, so theme, localization, directionality, and provider overrides are identical everywhere.

```dart
// test/helpers/test_app.dart
class TestApp extends StatelessWidget {
  const TestApp({
    super.key,
    required this.child,
    this.locale = const Locale('en'),
    this.brightness = Brightness.light,
    this.overrides = const [],
  });

  final Widget child;
  final Locale locale;
  final Brightness brightness;
  final List<Override> overrides;

  @override
  Widget build(BuildContext context) {
    return ProviderScope(
      overrides: overrides,
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        locale: locale,
        supportedLocales: AppLocalizations.supportedLocales,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        theme: buildTheme(brightness),
        home: Scaffold(body: child),
      ),
    );
  }
}
```

For screens that navigate, add a `TestRouterApp` variant that takes a `GoRouter` built from the real route table with `initialLocation`.

## 2. Widget tests: one per state

```dart
void main() {
  testWidgets('OrdersScreen shows skeleton while loading', (tester) async {
    await tester.pumpWidget(TestApp(
      overrides: [ordersControllerProvider.overrideWith(() => FakeOrders.loading())],
      child: const OrdersScreen(),
    ));
    expect(find.byType(OrdersSkeleton), findsOneWidget);
  });

  testWidgets('OrdersScreen shows empty state with a create action', (tester) async {
    await tester.pumpWidget(TestApp(
      overrides: [ordersControllerProvider.overrideWith(() => FakeOrders.data(const []))],
      child: const OrdersScreen(),
    ));
    await tester.pump();
    expect(find.byKey(const Key('orders.empty')), findsOneWidget);
    expect(find.byKey(const Key('orders.create')), findsOneWidget);
  });

  testWidgets('OrdersScreen shows the specific field error on validation failure', (tester) async {
    await tester.pumpWidget(TestApp(
      overrides: [ordersControllerProvider.overrideWith(
        () => FakeOrders.error(const ValidationFailure({'coupon': 'coupon_expired'})))],
      child: const OrdersScreen(),
    ));
    await tester.pump();
    expect(find.text(lookupAppLocalizations(const Locale('en')).couponExpired), findsOneWidget);
  });
}
```

Rules:
- Find by `Key` for anything a test depends on. Keys are namespaced strings (`orders.empty`), never generated.
- Text assertions use the localization lookup, not a hardcoded English string, so the same test runs under `ar`.
- `pumpAndSettle` only when an animation must finish; it hangs on infinite animations (spinners). Prefer `pump()` or `pump(duration)`.
- No real timers, no real network, no real platform channels. Fakes for repositories, `fake_async` or `clock` for time.
- A test that needs more than three provider overrides to render a screen is a design smell: the screen knows too much.

## 3. Goldens

### 3.1 Fonts first

Without loading fonts, golden text renders as solid boxes (the test font) and the golden proves nothing about typography, Arabic shaping, or truncation.

```dart
// test/flutter_test_config.dart : runs before every test file in the package
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  TestWidgetsFlutterBinding.ensureInitialized();
  await loadAppFonts();
  await testMain();
}

Future<void> loadAppFonts() async {
  final manifest = await AssetManifest.loadFromAssetBundle(rootBundle);
  // Map each bundled family to its files. Keep this list in sync with pubspec fonts.
  const families = {
    'AppSans': ['assets/fonts/AppSans-Regular.ttf', 'assets/fonts/AppSans-Medium.ttf', 'assets/fonts/AppSans-Bold.ttf'],
  };
  for (final entry in families.entries) {
    final loader = FontLoader(entry.key);
    for (final path in entry.value) {
      assert(manifest.listAssets().contains(path), 'Font asset missing from pubspec: $path');
      loader.addFont(rootBundle.load(path));
    }
    await loader.load();
  }
  // Material icons for icon rendering in goldens
  final icons = FontLoader('MaterialIcons')..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
  await icons.load();
}
```

`golden_toolkit` is discontinued. Use the loader above with `matchesGoldenFile`, or `alchemist` if you want scenario grids and CI/platform golden separation built in.

### 3.2 A golden matrix per screen

```dart
// test/goldens/order_card_golden_test.dart
@Tags(['golden'])
library;

void main() {
  final cases = [
    (name: 'en_light', locale: const Locale('en'), b: Brightness.light),
    (name: 'ar_light', locale: const Locale('ar'), b: Brightness.light),
    (name: 'ar_dark', locale: const Locale('ar'), b: Brightness.dark),
  ];
  const sizes = {'phone': Size(390, 844), 'small': Size(320, 640)};

  for (final c in cases) {
    for (final s in sizes.entries) {
      testWidgets('OrderCard ${c.name} ${s.key}', (tester) async {
        tester.view.physicalSize = s.value * 3;
        tester.view.devicePixelRatio = 3;
        addTearDown(tester.view.reset);

        await tester.pumpWidget(TestApp(
          locale: c.locale,
          brightness: c.b,
          child: const Center(child: OrderCard(order: Fixtures.longNameOrder)),
        ));
        await tester.pump();
        await expectLater(
          find.byType(OrderCard),
          matchesGoldenFile('goldens/order_card_${c.name}_${s.key}.png'),
        );
      });
    }
  }
}
```

What a golden matrix must include:
- LTR and RTL. The RTL golden is where padding, icon flipping, and truncation bugs appear.
- Light and dark for anything with color logic.
- The smallest supported width, with the longest realistic content (long names, large numbers, the longest translation). Overflow shows up here.
- Large text: one case with `MediaQuery(data: ...copyWith(textScaler: const TextScaler.linear(1.5)))` for screens users read.

### 3.3 Golden discipline

- Generate and compare on one platform. Rasterization differs between macOS, Linux, and Windows. Pick the CI runner OS and generate there (or in a container matching it). Local runs on another OS use `--exclude-tags golden` or a tolerant comparator, never `--update-goldens`.
- `flutter test --update-goldens --tags golden` only after a human has looked at the failure images in `test/goldens/failures/` and confirmed the change is intended. Commit the new PNGs in the same change as the UI edit, with the reason in the message.
- Keep goldens small: a component or a screen body, not a full device frame with status bar. Smaller images give focused diffs.
- Deterministic data: fixtures with fixed dates (inject a `Clock`), fixed IDs, no random avatars, no network images (override the image provider with a local asset).
- Animations and blinking carets: pump a fixed duration past animations, and render text fields in goldens with `showCursor: false` or unfocused.

## 4. Role and routing tests

For apps with several roles (see `role-switching.md`):

```dart
for (final role in Role.values) {
  testWidgets('a ${role.name} opening another role\'s route lands on their home', (tester) async {
    final router = buildRouter(fakeSession(active: membership(role)));
    await tester.pumpWidget(TestRouterApp(router: router));
    router.go(foreignRouteFor(role));
    await tester.pumpAndSettle();
    expect(router.routerDelegate.currentConfiguration.uri.path, homeFor(role));
  });
}
```

## 5. Integration tests

```dart
// integration_test/switch_role_test.dart
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('sign in, switch role, sign out', (tester) async {
    await app.main(env: TestEnv.staging());
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('signin.phone')), TestEnv.phone);
    await tester.tap(find.byKey(const Key('signin.submit')));
    await tester.pumpAndSettle();
    // ... OTP from the test backend, then:

    await tester.tap(find.byKey(const Key('profile.tab')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('switcher.owner')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('owner.home')), findsOneWidget);
  });
}
```

- Run against a seeded staging backend or a local fake server, never production.
- Use Patrol when the flow crosses native UI (permission dialogs, notifications, system share sheet); plain `integration_test` cannot tap those.
- Keep the suite to critical paths: sign in, the main money or data flow, role switch, sign out. Everything else belongs in widget tests.

## 6. CI

```bash
flutter analyze --fatal-infos
dart format --output=none --set-exit-if-changed .
flutter test --coverage --exclude-tags golden
flutter test --tags golden            # on the golden OS only
flutter test integration_test         # on an emulator or device job, critical paths only
```

Coverage gate: 80% or more on `domain/` and `presentation/controllers/`. Do not chase coverage on generated files; exclude `*.g.dart` and `*.freezed.dart` from the report.

## 7. Flaky test rules

- A flaky test is a failing test. Quarantine it with a tag and an issue link the same day, fix within the week.
- Common causes: `pumpAndSettle` on an infinite animation, real `DateTime.now()`, network images, shared mutable fakes between tests, test order dependence. Each has a fix above.

## 8. Checklist for a new screen

- [ ] Controller unit tests for every state transition
- [ ] Widget test per state: loading, empty, data, error (with the specific field message)
- [ ] Golden: en light, ar light, ar dark, at phone and smallest width, longest content
- [ ] Large text case for reading screens
- [ ] Role redirect test if the screen is role-gated
- [ ] Integration flow extended if the screen is on a critical path
