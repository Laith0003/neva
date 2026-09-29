---
name: "dart-flutter-patterns"
description: "Use when writing or structuring Flutter/Dart code: clean architecture layers, state management (Riverpod, BLoC), GoRouter guards, one app with role switching, RTL and Arabic, Dio networking, error handling, widget and golden tests."
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Dart/Flutter Patterns

Production patterns for Flutter apps that have to last: layered architecture, one state library used well, typed navigation, one app serving several roles, Arabic and RTL treated as a first-class layout, and tests that catch visual regressions before users do.

## When to Use

- Starting a Flutter app or feature and deciding structure, state management, routing, or data access
- Building one app that serves several roles (staff, owner, admin, customer) behind one login
- Shipping in Arabic or any RTL language, or mixing Arabic and Latin text, numbers, and phone numbers
- Writing or reviewing Dart for null safety, sealed types, records, and async composition
- Wiring Dio, token refresh, secure storage, and global error capture
- Writing unit, widget, golden, and integration tests

## Decisions This Skill Makes For You

| Question | Default | Switch when |
|---|---|---|
| Folder structure | Feature-first, each feature split into `data/`, `domain/`, `presentation/` | Tiny app with 1 to 3 screens: flat is fine |
| State management | Riverpod 3 with code generation (`@riverpod`) | Team already fluent in BLoC: keep BLoC, do not mix both |
| Models | Freezed 3 (`sealed` or `abstract` class) plus `json_serializable` | Dart macros or records cover it without codegen |
| Routing | `go_router` with typed routes (`go_router_builder`) and one central `redirect` | Deep nested flows that need a full `Router` delegate |
| HTTP | Dio with an auth interceptor and single-flight token refresh | Pure `http` package is fine for 1 or 2 endpoints |
| Secrets on device | `flutter_secure_storage` (Keychain, Android Keystore) | Never `shared_preferences` for tokens |
| Localization | `flutter_localizations` + `gen-l10n` ARB files, Arabic template first when Arabic is primary | none |
| Visual regression | Golden tests with bundled fonts, LTR and RTL variants, pinned device sizes | none |

## How It Works

Sections 1 to 10 are the core idioms. Sections 11 to 14 are the house patterns that most generated Flutter code gets wrong. Each has a deep reference:

| Topic | Section | Deep reference |
|---|---|---|
| Clean architecture, feature-first layout, dependency rule | 11 | `references/clean-architecture.md` |
| One app, many roles, Instagram-style account switching | 12 | `references/role-switching.md` |
| RTL and Arabic: directionality, fonts, digits, bidi, phone numbers | 13 | `references/rtl-arabic.md` |
| Widget, golden, and integration tests | 14 | `references/widget-and-golden-tests.md` |

Read the deep reference before writing code in that area. For review, use the `flutter-dart-code-review` skill or the `flutter-reviewer` agent. For design review of screens, pair with an HIG-grounded design review skill if one is installed.

## Examples

```dart
// Sealed state: impossible states are unrepresentable, switch is exhaustive
sealed class AsyncState<T> {}
final class Loading<T> extends AsyncState<T> {}
final class Success<T> extends AsyncState<T> { final T data; const Success(this.data); }
final class Failure<T> extends AsyncState<T> { final Object error; const Failure(this.error); }

// Directional spacing: never EdgeInsets.only(left:) in an app that may ship RTL
const EdgeInsetsDirectional.only(start: 16, end: 8);

// Riverpod derived provider with safe firstWhereOrNull (package:collection)
@riverpod
double cartTotal(Ref ref) {
  final cart = ref.watch(cartProvider);
  final products = ref.watch(productsProvider).value ?? const [];
  return cart.fold(0.0, (total, item) {
    final product = products.firstWhereOrNull((p) => p.id == item.productId);
    return total + (product?.price ?? 0) * item.quantity;
  });
}
```

Version notes: in Riverpod 3 `AsyncValue.value` returns the latest data or null and never throws (it replaced `valueOrNull`; use `requireValue` when absence is a bug), and generated providers take a plain `Ref`. In Freezed 3 the annotated class must be declared `sealed` or `abstract`. `GoRouterRefreshStream` is not shipped by `go_router`; write the small `ChangeNotifier` adapter shown in section 7.

---

## 1. Null Safety Fundamentals

### Prefer Patterns Over Bang Operator

```dart
// BAD: crashes at runtime if null
final name = user!.name;

// GOOD: provide fallback
final name = user?.name ?? 'Unknown';

// GOOD: Dart 3 pattern matching (preferred for complex cases)
final display = switch (user) {
  User(:final name, :final email) => '$name <$email>',
  null => 'Guest',
};

// GOOD: guard early return
String getUserName(User? user) {
  if (user == null) return 'Unknown';
  return user.name; // promoted to non-null after check
}
```

### Avoid `late` Overuse

```dart
// BAD: defers null error to runtime
late String userId;

// GOOD: nullable with explicit initialization
String? userId;

// OK: use late only when initialization is guaranteed before first access
// (e.g., in initState() before any widget interaction)
late final AnimationController _controller;

@override
void initState() {
  super.initState();
  _controller = AnimationController(vsync: this, duration: const Duration(milliseconds: 300));
}
```

---

## 2. Immutable State

### Sealed Classes for State Hierarchies

```dart
sealed class UserState {}

final class UserInitial extends UserState {}

final class UserLoading extends UserState {}

final class UserLoaded extends UserState {
  const UserLoaded(this.user);
  final User user;
}

final class UserError extends UserState {
  const UserError(this.message);
  final String message;
}

// Exhaustive switch: compiler enforces all branches
Widget buildFrom(UserState state) => switch (state) {
  UserInitial() => const SizedBox.shrink(),
  UserLoading() => const CircularProgressIndicator(),
  UserLoaded(:final user) => UserCard(user: user),
  UserError(:final message) => ErrorText(message),
};
```

### Freezed for Boilerplate-Free Immutability

```dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'user.freezed.dart';
part 'user.g.dart';

@freezed
abstract class User with _$User { // Freezed 3: `abstract` for one constructor, `sealed` for unions
  const factory User({
    required String id,
    required String name,
    required String email,
    @Default(false) bool isAdmin,
  }) = _User;

  factory User.fromJson(Map<String, dynamic> json) => _$UserFromJson(json);
}

// Usage
final user = User(id: '1', name: 'Alice', email: 'alice@example.com');
final updated = user.copyWith(name: 'Alice Smith'); // immutable update
final json = user.toJson();
final fromJson = User.fromJson(json);
```

---

## 3. Async Composition

### Structured Concurrency with Future.wait

```dart
Future<DashboardData> loadDashboard(UserRepository users, OrderRepository orders) async {
  // Run concurrently: don't await sequentially
  final (userList, orderList) = await (
    users.getAll(),
    orders.getRecent(),
  ).wait; // Dart 3 record destructuring + Future.wait extension

  return DashboardData(users: userList, orders: orderList);
}
```

### Stream Patterns

```dart
// Repository exposes reactive streams for live data
Stream<List<Item>> watchCartItems() => _db
    .watchTable('cart_items')
    .map((rows) => rows.map(Item.fromRow).toList());

// In widget layer: declarative, no manual subscription
StreamBuilder<List<Item>>(
  stream: cartRepository.watchCartItems(),
  builder: (context, snapshot) => switch (snapshot) {
    AsyncSnapshot(connectionState: ConnectionState.waiting) =>
        const CircularProgressIndicator(),
    AsyncSnapshot(:final error?) => ErrorWidget(error.toString()),
    AsyncSnapshot(:final data?) => CartList(items: data),
    _ => const SizedBox.shrink(),
  },
)
```

### BuildContext After Await

```dart
// CRITICAL: always check mounted after any await in StatefulWidget
Future<void> _handleSubmit() async {
  setState(() => _isLoading = true);
  try {
    await authService.login(_email, _password);
    if (!mounted) return; // ← guard before using context
    context.go('/home');
  } on AuthException catch (e) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
  } finally {
    if (mounted) setState(() => _isLoading = false);
  }
}
```

---

## 4. Widget Architecture

### Extract to Classes, Not Methods

```dart
// BAD: private method returning widget, prevents optimization
Widget _buildHeader() {
  return Container(
    padding: const EdgeInsets.all(16),
    child: Text(title, style: Theme.of(context).textTheme.headlineMedium),
  );
}

// GOOD: separate widget class, enables const, element reuse
class _PageHeader extends StatelessWidget {
  const _PageHeader(this.title);
  final String title;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      child: Text(title, style: Theme.of(context).textTheme.headlineMedium),
    );
  }
}
```

### const Propagation

```dart
// BAD: new instances every rebuild
child: Padding(
  padding: EdgeInsets.all(16.0),       // not const
  child: Icon(Icons.home, size: 24.0), // not const
)

// GOOD: const stops rebuild propagation
child: const Padding(
  padding: EdgeInsets.all(16.0),
  child: Icon(Icons.home, size: 24.0),
)
```

### Scoped Rebuilds

```dart
// BAD: entire page rebuilds on every counter change
class CounterPage extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final count = ref.watch(counterProvider); // rebuilds everything
    return Scaffold(
      body: Column(children: [
        const ExpensiveHeader(), // unnecessarily rebuilt
        Text('$count'),
        const ExpensiveFooter(), // unnecessarily rebuilt
      ]),
    );
  }
}

// GOOD: isolate the rebuilding part
class CounterPage extends StatelessWidget {
  const CounterPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Column(children: [
        ExpensiveHeader(),        // never rebuilt (const)
        _CounterDisplay(),        // only this rebuilds
        ExpensiveFooter(),        // never rebuilt (const)
      ]),
    );
  }
}

class _CounterDisplay extends ConsumerWidget {
  const _CounterDisplay();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final count = ref.watch(counterProvider);
    return Text('$count');
  }
}
```

---

## 5. State Management: BLoC/Cubit

```dart
// Cubit: synchronous or simple async state
class AuthCubit extends Cubit<AuthState> {
  AuthCubit(this._authService) : super(const AuthState.initial());
  final AuthService _authService;

  Future<void> login(String email, String password) async {
    emit(const AuthState.loading());
    try {
      final user = await _authService.login(email, password);
      emit(AuthState.authenticated(user));
    } on AuthException catch (e) {
      emit(AuthState.error(e.message));
    }
  }

  void logout() {
    _authService.logout();
    emit(const AuthState.initial());
  }
}

// In widget
BlocBuilder<AuthCubit, AuthState>(
  builder: (context, state) => switch (state) {
    AuthInitial() => const LoginForm(),
    AuthLoading() => const CircularProgressIndicator(),
    AuthAuthenticated(:final user) => HomePage(user: user),
    AuthError(:final message) => ErrorView(message: message),
  },
)
```

---

## 6. State Management: Riverpod

```dart
// Auto-dispose async provider
@riverpod
Future<List<Product>> products(Ref ref) async {
  final repo = ref.watch(productRepositoryProvider);
  return repo.getAll();
}

// Notifier with complex mutations
@riverpod
class CartNotifier extends _$CartNotifier {
  @override
  List<CartItem> build() => [];

  void add(Product product) {
    final existing = state.where((i) => i.productId == product.id).firstOrNull;
    if (existing != null) {
      state = [
        for (final item in state)
          if (item.productId == product.id) item.copyWith(quantity: item.quantity + 1)
          else item,
      ];
    } else {
      state = [...state, CartItem(productId: product.id, quantity: 1)];
    }
  }

  void remove(String productId) =>
      state = state.where((i) => i.productId != productId).toList();

  void clear() => state = [];
}

// Derived provider (selector pattern)
@riverpod
int cartCount(Ref ref) => ref.watch(cartNotifierProvider).length;

@riverpod
double cartTotal(Ref ref) {
  final cart = ref.watch(cartNotifierProvider);
  final products = ref.watch(productsProvider).value ?? const []; // Riverpod 3: latest data or null, never throws
  return cart.fold(0.0, (total, item) {
    // firstWhereOrNull (from collection package) avoids StateError when product is missing
    final product = products.firstWhereOrNull((p) => p.id == item.productId);
    return total + (product?.price ?? 0) * item.quantity;
  });
}
```

---

## 7. Navigation with GoRouter

`go_router` does not ship a stream adapter. Write it once:

```dart
class GoRouterRefreshStream extends ChangeNotifier {
  GoRouterRefreshStream(Stream<dynamic> stream) {
    _sub = stream.asBroadcastStream().listen((_) => notifyListeners());
  }
  late final StreamSubscription<dynamic> _sub;

  @override
  void dispose() {
    _sub.cancel();
    super.dispose();
  }
}
```

Keep all access rules in the single `redirect`. Screens never check auth or role themselves. For typed routes, generate them with `go_router_builder` so a missing path parameter is a compile error, not a runtime `!`.

```dart
final router = GoRouter(
  initialLocation: '/',
  // refreshListenable re-evaluates redirect whenever auth state changes
  refreshListenable: GoRouterRefreshStream(authCubit.stream),
  redirect: (context, state) {
    final isLoggedIn = context.read<AuthCubit>().state is AuthAuthenticated;
    final isGoingToLogin = state.matchedLocation == '/login';
    if (!isLoggedIn && !isGoingToLogin) return '/login';
    if (isLoggedIn && isGoingToLogin) return '/';
    return null;
  },
  routes: [
    GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
    ShellRoute(
      builder: (context, state, child) => AppShell(child: child),
      routes: [
        GoRoute(path: '/', builder: (_, __) => const HomePage()),
        GoRoute(
          path: '/products/:id',
          builder: (context, state) =>
              ProductDetailPage(id: state.pathParameters['id']!),
        ),
      ],
    ),
  ],
);
```

---

## 8. HTTP with Dio

```dart
final dio = Dio(BaseOptions(
  baseUrl: const String.fromEnvironment('API_URL'),
  connectTimeout: const Duration(seconds: 10),
  receiveTimeout: const Duration(seconds: 30),
  headers: {'Content-Type': 'application/json'},
));

// Add auth interceptor.
// Single-flight refresh: when five requests hit 401 at once, only ONE refresh call goes out.
// The full version, with per-account tokens, is in references/role-switching.md.
Future<bool>? _refreshInFlight;
Future<bool> attemptTokenRefresh() =>
    _refreshInFlight ??= _doRefresh().whenComplete(() => _refreshInFlight = null);

dio.interceptors.add(InterceptorsWrapper(
  onRequest: (options, handler) async {
    final token = await secureStorage.read(key: 'auth_token');
    if (token != null) options.headers['Authorization'] = 'Bearer $token';
    handler.next(options);
  },
  onError: (error, handler) async {
    // Guard against infinite retry loops: only attempt refresh once per request
    final isRetry = error.requestOptions.extra['_isRetry'] == true;
    if (!isRetry && error.response?.statusCode == 401) {
      final refreshed = await attemptTokenRefresh();
      if (refreshed) {
        error.requestOptions.extra['_isRetry'] = true;
        return handler.resolve(await dio.fetch(error.requestOptions));
      }
    }
    handler.next(error);
  },
));

// Repository using Dio
class UserApiDataSource {
  const UserApiDataSource(this._dio);
  final Dio _dio;

  Future<User> getById(String id) async {
    final response = await _dio.get<Map<String, dynamic>>('/users/$id');
    return User.fromJson(response.data!);
  }
}
```

---

## 9. Error Handling Architecture

```dart
// Global error capture: set up in main()
void main() {
  FlutterError.onError = (details) {
    FlutterError.presentError(details);
    crashlytics.recordFlutterFatalError(details);
  };

  PlatformDispatcher.instance.onError = (error, stack) {
    crashlytics.recordError(error, stack, fatal: true);
    return true;
  };

  // Release-mode replacement for the red error screen. Set once, here, not inside build().
  if (kReleaseMode) ErrorWidget.builder = (details) => const ProductionErrorWidget();

  runApp(const ProviderScope(child: App()));
}
```

---

## 10. Testing Quick Reference

```dart
// Unit test: use case
test('GetUserUseCase returns null for missing user', () async {
  final repo = FakeUserRepository();
  final useCase = GetUserUseCase(repo);
  expect(await useCase('missing-id'), isNull);
});

// BLoC test
blocTest<AuthCubit, AuthState>(
  'emits loading then error on failed login',
  build: () => AuthCubit(FakeAuthService(throwsOn: 'login')),
  act: (cubit) => cubit.login('user@example.com', 'wrong'),
  expect: () => [const AuthState.loading(), isA<AuthError>()],
);

// Widget test
testWidgets('CartBadge shows item count', (tester) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [cartNotifierProvider.overrideWith(() => FakeCartNotifier(count: 3))],
      child: const MaterialApp(home: CartBadge()),
    ),
  );
  expect(find.text('3'), findsOneWidget);
});
```

---

## 11. Clean Architecture, Feature-First

Structure by feature, then by layer inside each feature. The dependency rule points inward: `presentation` depends on `domain`, `data` depends on `domain`, `domain` depends on nothing Flutter.

```
lib/
  app/                 # MaterialApp.router, theme, router, l10n wiring, bootstrap
  core/                # cross-cutting: http client, secure storage, result type, logging, design tokens
  features/
    orders/
      domain/          # entities, repository interfaces, use cases. Pure Dart, no Flutter import.
      data/            # DTOs, API and local data sources, repository implementations, mappers
      presentation/    # screens, widgets, controllers (Notifier/Cubit), view state
  l10n/                # app_ar.arb, app_en.arb
test/                  # mirrors lib/
```

Gates (enforce in review, and with `import_lint` or a custom lint if the team is large):
- `domain/` imports no `package:flutter`, no `dio`, no JSON annotations. If it does, the layer is leaking.
- Widgets never call a repository or `Dio` directly. They read a controller.
- DTOs never reach a widget. Map DTO to entity in `data/`.
- A feature never imports another feature's `data/` or `presentation/`. Share through `core/` or a domain interface.
- Errors cross layers as typed failures (sealed `Failure`), never as raw `DioException`.

Full layout, the `Result` type, mappers, and when a use case is worth it: `references/clean-architecture.md`.

## 12. One App, Many Roles

When the same person can be staff at one business, owner of another, and a customer, ship ONE app with account switching, not one app per role. The model is an Instagram-style account switcher: one identity, many memberships, one active context.

```dart
enum Role { staff, owner, admin, customer }

@freezed
abstract class Membership with _$Membership {
  const factory Membership({
    required String id,          // membership id, not user id
    required Role role,
    required String tenantId,    // the business or workspace this role applies to
    required String displayName,
  }) = _Membership;
}

@Riverpod(keepAlive: true)
class ActiveMembership extends _$ActiveMembership {
  @override
  Membership? build() => null; // restored from secure storage at bootstrap

  Future<void> switchTo(Membership next) async {
    await ref.read(sessionStoreProvider).setActive(next.id);
    state = next;
    // Invalidate everything scoped to the previous tenant so no data leaks across roles.
    ref.invalidate(tenantScopeProvider);
  }
}
```

Rules:
- The server decides which memberships exist and re-checks role on every request. The client role is a UI hint, never an authorization.
- One `redirect` maps (auth state, active role, location) to an allowed location. Each role gets its own `StatefulShellRoute` branch set so tabs and back stacks do not bleed between roles.
- Every provider that holds tenant data depends on `tenantScopeProvider`, so a switch invalidates it in one call.
- Switching is a full context change: clear in-memory caches, cancel in-flight requests for the old tenant, reset navigation to the new role's home.
- Show the active role and tenant at all times (avatar plus name in the app bar), and make the switcher reachable in one tap or one long-press on the profile tab.

Full pattern with router branches, per-account token storage, single-flight refresh, and tests: `references/role-switching.md`.

## 13. RTL and Arabic

An RTL app is not a mirrored LTR app with translated strings. Build directional from the first widget.

```dart
MaterialApp.router(
  locale: const Locale('ar'),
  supportedLocales: AppLocalizations.supportedLocales,
  localizationsDelegates: AppLocalizations.localizationsDelegates, // includes GlobalMaterialLocalizations
  routerConfig: router,
);

// Directional everything
const EdgeInsetsDirectional.only(start: 16);        // not EdgeInsets.only(left: 16)
AlignmentDirectional.centerStart;                   // not Alignment.centerLeft
PositionedDirectional(start: 0, child: badge);      // not Positioned(left: 0)
BorderRadiusDirectional.only(topStart: Radius.circular(12));
Icon(Icons.arrow_back);                             // Material flips it in RTL; custom SVG arrows must flip too

// Phone numbers, codes, and IDs are always LTR, even inside Arabic text
Text('\u2066$phone\u2069');                         // LRI/PDI isolate; or Directionality(textDirection: TextDirection.ltr)
```

Rules:
- Ban `EdgeInsets.only(left:/right:)`, `Alignment.*Left/*Right`, `Positioned(left:/right:)`, and `TextAlign.left/right` in feature code. Use `start`/`end`.
- Pick an Arabic-capable font with real weights and set it in `ThemeData.fontFamily`, bundled as an asset (no runtime fetch). Arabic needs more line height than Latin: tune `height` in the text theme, never per widget.
- Never apply `letterSpacing` to Arabic text: it breaks the joins.
- Decide digits deliberately: Western digits (0 to 9) or Arabic-Indic, per product, and format through `intl` `NumberFormat` for that locale. Never mix within one screen.
- Plurals use ICU in ARB. Arabic has six plural forms (zero, one, two, few, many, other); supply all of them.
- Test every screen in both directions (section 14). The RTL golden is where layout bugs show up.

Full guide with the lint list, bidi cases, input fields, charts, and icons that must or must not flip: `references/rtl-arabic.md`.

## 14. Widget, Golden, and Integration Tests

Three layers, each with a job:

| Layer | Proves | Tool |
|---|---|---|
| Unit | domain and controller logic, every state transition | `test`, `bloc_test` or `ProviderContainer` |
| Widget | a screen renders each state and reacts to taps | `flutter_test` with provider overrides |
| Golden | pixels did not change by accident, in LTR and RTL, light and dark | `matchesGoldenFile`, optionally `alchemist` |
| Integration | a real flow on a device: login, switch role, complete a task | `integration_test` (or Patrol for native dialogs) |

```dart
// Golden, both directions, fonts loaded, fixed size
for (final dir in TextDirection.values) {
  testWidgets('OrderCard golden ${dir.name}', (tester) async {
    await loadAppFonts(); // helper in the reference: loads bundled fonts, else text renders as boxes
    tester.view.physicalSize = const Size(1170, 2532); // 390 x 844 logical at 3x
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(TestApp(
      locale: dir == TextDirection.rtl ? const Locale('ar') : const Locale('en'),
      child: const OrderCard(order: fixtureOrder),
    ));
    await expectLater(find.byType(OrderCard), matchesGoldenFile('goldens/order_card_${dir.name}.png'));
  });
}
```

Rules:
- Goldens are generated on ONE platform (CI Linux, or a pinned macOS runner) and compared there. Font rasterization differs per OS.
- `flutter test --update-goldens` only after a human looked at the diff and the change was intended.
- Every screen: one widget test per state (loading, empty, data, error). Every role-gated screen: a test that the wrong role is redirected.
- Fakes over mocks. Override providers, never reach into globals.

Full harness (`TestApp`, font loading, `alchemist` setup, CI config, flaky-test rules): `references/widget-and-golden-tests.md`.

---

## References

- [Effective Dart: Design](https://dart.dev/effective-dart/design)
- [Flutter Performance Best Practices](https://docs.flutter.dev/perf/best-practices)
- [Riverpod Documentation](https://riverpod.dev/)
- [BLoC Library](https://bloclibrary.dev/)
- [GoRouter](https://pub.dev/packages/go_router)
- [Freezed](https://pub.dev/packages/freezed)
- [Flutter internationalization](https://docs.flutter.dev/ui/accessibility-and-internationalization/internationalization)
- [Flutter testing overview](https://docs.flutter.dev/testing/overview)
- Skill: `flutter-dart-code-review`, comprehensive review checklist
- Rules: `rules/dart/`, coding style, patterns, security, testing, hooks
