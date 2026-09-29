# One App, Many Roles: Account Switching in Flutter

<!-- Written for Neva as an extension of the dart-flutter-patterns skill adapted from affaan-m/ECC (MIT), commit d3b8a3e. -->

Use this when one person can act in more than one capacity: staff at a counter, owner of a business, platform admin, and later a plain customer. Ship one app with an Instagram-style switcher, not four apps. One login, many memberships, one active context at a time.

## 1. The model

```
Identity (who you are: one per person, one login)
  └── Membership (what you can do, where)  x N
        role:   staff | owner | admin | customer
        tenant: the business, branch, or workspace the role applies to
ActiveContext = exactly one Membership, or none (signed in, no role picked yet)
```

```dart
enum Role { staff, owner, admin, customer }

@freezed
abstract class Membership with _$Membership {
  const factory Membership({
    required String id,
    required Role role,
    required String tenantId,
    required String tenantName,
    String? tenantLogoUrl,
  }) = _Membership;

  factory Membership.fromJson(Map<String, dynamic> json) => _$MembershipFromJson(json);
}

@freezed
sealed class SessionState with _$SessionState {
  const factory SessionState.signedOut() = SignedOut;
  const factory SessionState.signedIn({
    required String identityId,
    required List<Membership> memberships,
    Membership? active,
  }) = SignedIn;
}
```

Why memberships and not a `role` field on the user: the same person holds different roles at different tenants, roles are granted and revoked independently, and an admin may also be a customer. A single enum on the user cannot express any of that.

## 2. Authorization lives on the server

The client role is a UI hint. Every request carries the active membership id (header such as `X-Membership-Id`, or a membership-scoped token), and the server re-checks that the identity holds that membership and that the role permits the action. A tampered client must not be able to act as owner by flipping a local value.

## 3. Session controller

```dart
@Riverpod(keepAlive: true)
class Session extends _$Session {
  @override
  Future<SessionState> build() async {
    final store = ref.watch(sessionStoreProvider);
    final restored = await store.restore();          // secure storage: identity, tokens, last active membership id
    if (restored == null) return const SessionState.signedOut();
    final memberships = await ref.read(authApiProvider).memberships();   // server truth, not the cache
    final active = memberships.firstWhereOrNull((m) => m.id == restored.activeMembershipId)
        ?? (memberships.length == 1 ? memberships.single : null);       // auto-pick only when unambiguous
    return SessionState.signedIn(identityId: restored.identityId, memberships: memberships, active: active);
  }

  Future<void> switchTo(Membership next) async {
    final current = state.value;
    if (current is! SignedIn || !current.memberships.contains(next)) {
      throw StateError('switchTo: membership ${next.id} is not held by this identity');
    }
    ref.read(inFlightRequestsProvider).cancelAll('role switch');   // no old-tenant response lands in the new context
    await ref.read(sessionStoreProvider).setActive(next.id);
    state = AsyncData(current.copyWith(active: next));
    ref.invalidate(tenantScopeProvider);                           // every tenant-scoped provider rebuilds
  }

  Future<void> signOut() async {
    ref.read(inFlightRequestsProvider).cancelAll('sign out');
    await ref.read(sessionStoreProvider).clearAll();
    state = const AsyncData(SessionState.signedOut());
    ref.invalidate(tenantScopeProvider);
  }
}

/// The one thing tenant-scoped providers watch. Throws if read with no active membership,
/// which surfaces a routing bug immediately instead of showing another tenant's data.
@Riverpod(keepAlive: true)
Membership tenantScope(Ref ref) {
  final session = ref.watch(sessionProvider).value;
  return switch (session) {
    SignedIn(active: final m?) => m,
    _ => throw StateError('tenantScope read without an active membership'),
  };
}
```

Rule: any provider that holds data belonging to a tenant must `ref.watch(tenantScopeProvider)`. That single dependency is what makes a switch safe: invalidate the scope, and every dependent provider disposes and rebuilds against the new tenant.

## 4. Router: one redirect, one shell per role

```dart
final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier<int>(0);
  ref.listen(sessionProvider, (_, __) => refresh.value++);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: '/',
    refreshListenable: refresh,
    redirect: (context, state) {
      final session = ref.read(sessionProvider);
      final loc = state.matchedLocation;
      return switch (session) {
        AsyncLoading() => loc == '/splash' ? null : '/splash',
        AsyncError() => '/signin',
        AsyncData(value: SignedOut()) => loc.startsWith('/signin') ? null : '/signin',
        AsyncData(value: SignedIn(active: null)) => loc == '/choose-role' ? null : '/choose-role',
        AsyncData(value: SignedIn(active: final m?)) => allowed(m.role, loc) ? null : homeFor(m.role),
      };
    },
    routes: [
      GoRoute(path: '/splash', builder: (_, __) => const SplashScreen()),
      GoRoute(path: '/signin', builder: (_, __) => const SignInScreen()),
      GoRoute(path: '/choose-role', builder: (_, __) => const ChooseRoleScreen()),
      staffShell,     // StatefulShellRoute.indexedStack under /staff
      ownerShell,     // under /owner
      adminShell,     // under /admin
      customerShell,  // under /c
    ],
  );
});

bool allowed(Role role, String loc) => switch (role) {
  Role.staff => loc.startsWith('/staff') || loc.startsWith('/account'),
  Role.owner => loc.startsWith('/owner') || loc.startsWith('/account'),
  Role.admin => loc.startsWith('/admin') || loc.startsWith('/account'),
  Role.customer => loc.startsWith('/c') || loc.startsWith('/account'),
};

String homeFor(Role role) => switch (role) {
  Role.staff => '/staff',
  Role.owner => '/owner',
  Role.admin => '/admin',
  Role.customer => '/c',
};
```

Why a shell per role: each role has its own tabs and its own back stacks. `StatefulShellRoute.indexedStack` preserves each tab's state inside a role, and because roles live under different path prefixes, switching roles cannot pop you into the previous role's stack.

Deep links: a link to `/owner/reports/42` opened while the active role is staff hits the redirect. If the identity holds an owner membership for that tenant, offer the switch ("Open as owner of Branch X?"); never switch silently.

## 5. The switcher UI

- The active role and tenant are visible on every screen: avatar or logo plus name in the app bar or the profile tab.
- One tap on the profile tab opens the switcher sheet; long-press switches to the last used membership (the Instagram gesture).
- The sheet lists memberships grouped by tenant, the active one marked, each row showing role and tenant name. Add a "Sign out" row at the bottom, separated.
- After a switch, show a brief, specific confirmation: "Now working as Owner, Branch X". Reset to that role's home tab.
- Staff mode on a shared counter device: add an idle lock back to the staff PIN or sign-in screen, and never cache the owner context on that device.

## 6. Tokens per account

If the backend issues one token per identity with membership passed per request, store one token pair. If it issues membership-scoped tokens, store a map `membershipId -> TokenPair` in secure storage and pick by the active membership in the interceptor.

```dart
class AuthInterceptor extends QueuedInterceptor {   // queued: requests wait while a refresh runs
  AuthInterceptor(this._ref, this._dio);
  final Ref _ref;
  final Dio _dio;
  Future<bool>? _refreshing;

  @override
  Future<void> onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    final active = _ref.read(sessionProvider).value;
    if (active case SignedIn(active: final m?)) {
      final tokens = await _ref.read(sessionStoreProvider).tokensFor(m.id);
      if (tokens != null) options.headers['Authorization'] = 'Bearer ${tokens.access}';
      options.headers['X-Membership-Id'] = m.id;
    }
    handler.next(options);
  }

  @override
  Future<void> onError(DioException err, ErrorInterceptorHandler handler) async {
    final retried = err.requestOptions.extra['retried'] == true;
    if (err.response?.statusCode != 401 || retried) return handler.next(err);

    // Single flight: concurrent 401s share one refresh call.
    final ok = await (_refreshing ??= _refresh().whenComplete(() => _refreshing = null));
    if (!ok) {
      await _ref.read(sessionProvider.notifier).signOut();
      return handler.next(err);
    }
    final retry = err.requestOptions..extra['retried'] = true;
    handler.resolve(await _dio.fetch(retry));
  }

  Future<bool> _refresh() async { /* call refresh endpoint with a separate Dio without this interceptor */ return true; }
}
```

The refresh call must use a separate `Dio` instance without this interceptor, or a failing refresh recurses.

## 7. Tests that must exist

- Unit: `switchTo` rejects a membership the identity does not hold, persists the active id, and invalidates `tenantScopeProvider`.
- Unit: a provider that watches `tenantScopeProvider` returns tenant B data after a switch from A, and never A data.
- Widget: for each role, a location from another role redirects to that role's home.
- Widget: a signed-in identity with two memberships and no active one lands on `/choose-role`; with exactly one, it lands on that role's home.
- Golden: the switcher sheet in LTR and RTL.
- Integration: sign in, switch role, confirm the tab bar and the data both changed, sign out, confirm secure storage is empty.

## 8. Anti-patterns

| Anti-pattern | Why it breaks | Do instead |
|---|---|---|
| `if (user.isAdmin)` checks inside screens | Role logic scattered, deep links bypass it | One `redirect` plus `allowed()` |
| One global `role` string in shared preferences | Tamperable, not per tenant, survives sign-out | Membership list from the server, active id in secure storage |
| Separate apps per role | Double release work, a person with two roles juggles two apps | One app, memberships, switcher |
| Keeping tenant data in `keepAlive` providers that do not watch the scope | Tenant A data shows up after switching to B | Every tenant provider watches `tenantScopeProvider` |
| Switching silently on a deep link | User acts in the wrong capacity | Ask before switching |
