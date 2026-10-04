# Clean Architecture for Flutter, Feature-First

<!-- Written for Neva as an extension of the dart-flutter-patterns skill adapted from affaan-m/ECC (MIT), commit d3b8a3e. -->

The goal is a codebase where a new engineer can find any behavior in two hops (feature, then layer), where business rules are testable without a device, and where swapping an API, a cache, or a state library touches one layer.

## 1. The layout

```
lib/
  main.dart                       # calls bootstrap(), nothing else
  app/
    bootstrap.dart                # error zones, env, secure storage restore, ProviderScope
    app.dart                      # MaterialApp.router, theme, locale, l10n delegates
    router/
      router.dart                 # GoRouter, the ONE redirect
      routes.dart                 # typed routes (go_router_builder)
  core/
    network/                      # Dio factory, interceptors, error mapper
    storage/                      # secure storage wrapper, session store
    result/                       # Result<T>, Failure hierarchy
    design/                       # tokens: color, type scale, spacing, radius, motion
    l10n/                         # formatting helpers (numbers, dates, phone)
    widgets/                      # shared, dumb UI pieces only
  features/
    <feature>/
      domain/
        entities/                 # immutable business objects
        repositories/             # abstract interfaces
        usecases/                 # only when there is real orchestration
      data/
        dtos/                     # JSON shapes, json_serializable
        sources/                  # remote (Dio) and local (drift, isar, hive) sources
        mappers/                  # DTO <-> entity
        repositories/             # implementations of domain interfaces
      presentation/
        controllers/              # Notifier / AsyncNotifier / Cubit
        screens/
        widgets/
  l10n/
    app_ar.arb
    app_en.arb
test/                             # mirrors lib/, plus test/helpers/ and test/goldens/
integration_test/
```

Feature-first beats layer-first once the app has more than about five screens: a change to "orders" stays inside `features/orders/`, and deleting a feature is deleting a folder.

## 2. The dependency rule

```
presentation  ->  domain  <-  data
        \                    /
         ----->  core  <-----
```

| Layer | May import | Must not import |
|---|---|---|
| `domain` | Dart SDK, `core/result`, `freezed_annotation` if you use it for entities | `package:flutter`, `dio`, `json_annotation`, any `data/` or `presentation/` |
| `data` | `domain`, `core`, `dio`, persistence packages | `presentation`, `package:flutter/widgets.dart` |
| `presentation` | `domain`, `core`, Flutter, state library | `data/` of any feature (reach it only through providers wired in DI) |

Enforce it. Options, cheapest first:
1. Review checklist (the `flutter-dart-code-review` skill has the items).
2. A CI grep that fails on `import 'package:flutter` under `lib/features/*/domain/`.
3. A custom lint (`custom_lint`) or `import_lint` rules per folder.

## 3. Result and failures

Errors cross layer boundaries as values, not exceptions.

```dart
sealed class Failure implements Exception { // implements Exception so it can be thrown into AsyncValue.error
  const Failure();
}
final class NetworkFailure extends Failure { const NetworkFailure(); }
final class UnauthorizedFailure extends Failure { const UnauthorizedFailure(); }
final class ValidationFailure extends Failure {
  const ValidationFailure(this.fieldErrors); // field name -> message key
  final Map<String, String> fieldErrors;
}
final class ServerFailure extends Failure {
  const ServerFailure(this.code);
  final String code;
}

sealed class Result<T> {
  const Result();
}
final class Ok<T> extends Result<T> { const Ok(this.value); final T value; }
final class Err<T> extends Result<T> { const Err(this.failure); final Failure failure; }
```

The data layer catches `DioException` exactly once, in a mapper, and returns `Err(...)`. `ValidationFailure` carries per-field messages so the UI can show the specific field and the fix, never a generic "something went wrong".

```dart
Failure mapDioError(DioException e) => switch (e) {
  DioException(type: DioExceptionType.connectionTimeout || DioExceptionType.connectionError) =>
      const NetworkFailure(),
  DioException(response: Response(statusCode: 401)) => const UnauthorizedFailure(),
  DioException(response: Response(statusCode: 422, :final data?)) =>
      ValidationFailure(parseFieldErrors(data)),
  DioException(response: Response(:final statusCode)) => ServerFailure('http_$statusCode'),
  _ => const ServerFailure('unknown'),
};
```

## 4. Repositories

```dart
// domain/repositories/order_repository.dart
abstract interface class OrderRepository {
  Future<Result<List<Order>>> recent({required String tenantId});
  Stream<List<Order>> watchOpen({required String tenantId});
}

// data/repositories/order_repository_impl.dart
final class OrderRepositoryImpl implements OrderRepository {
  OrderRepositoryImpl(this._remote, this._local);
  final OrderRemoteSource _remote;
  final OrderLocalSource _local;

  @override
  Future<Result<List<Order>>> recent({required String tenantId}) async {
    try {
      final dtos = await _remote.recent(tenantId);
      await _local.upsertAll(dtos);
      return Ok(dtos.map(OrderMapper.toEntity).toList(growable: false));
    } on DioException catch (e) {
      return Err(mapDioError(e));
    }
  }

  @override
  Stream<List<Order>> watchOpen({required String tenantId}) =>
      _local.watchOpen(tenantId).map((rows) => rows.map(OrderMapper.fromRow).toList());
}
```

Offline-first read path: the UI watches the local store; the repository refreshes it from the network. The screen never waits on the network to show something.

## 5. Use cases: only when they earn it

A use case that forwards one call to one repository is noise. Write one when it:
- orchestrates two or more repositories or services,
- enforces a business rule that must be tested alone (limits, eligibility, idempotency keys),
- or is called from more than one controller.

```dart
final class PlaceOrder {
  PlaceOrder(this._cart, this._orders, this._clock);
  final CartRepository _cart;
  final OrderRepository _orders;
  final Clock _clock;

  Future<Result<Receipt>> call({required String tenantId, required String couponCode}) async {
    final coupon = await _cart.coupon(couponCode);
    if (coupon case Err(:final failure)) return Err(failure);
    final c = (coupon as Ok<Coupon>).value;
    if (c.expiresAt.isBefore(_clock.now())) {
      return const Err(ValidationFailure({'coupon': 'coupon_expired'}));
    }
    return _orders.place(tenantId: tenantId, coupon: c, idempotencyKey: newKey());
  }
}
```

## 6. Controllers and view state

```dart
@riverpod
class OrdersController extends _$OrdersController {
  @override
  Future<List<Order>> build() async {
    final tenant = ref.watch(tenantScopeProvider);           // re-runs on role switch
    final result = await ref.watch(orderRepositoryProvider).recent(tenantId: tenant.id);
    return switch (result) {
      Ok(:final value) => value,
      Err(:final failure) => throw failure,                  // AsyncValue.error carries the typed Failure
    };
  }

  Future<void> refresh() async {
    ref.invalidateSelf();   // keeps previous data visible while reloading
    await future;
  }
}
```

In the screen, switch exhaustively on `AsyncValue` and on the `Failure` type to pick the message. One message key per failure type, localized.

## 7. Dependency injection

With Riverpod the provider graph is the DI container. Rules:
- One provider per abstraction, typed as the interface: `OrderRepository`, not `OrderRepositoryImpl`.
- Environment differences (base URL, logging level) come from `--dart-define` read once in `bootstrap.dart`, then provided. No `if (kDebugMode)` inside repositories.
- Tests override the interface provider with a fake. If a test needs to override more than three providers to render one screen, the screen knows too much.

With BLoC: `RepositoryProvider` at the app root, `BlocProvider` at the route that owns the feature, blocs never construct their own repositories.

## 8. Checklist

- [ ] `domain/` has zero Flutter or HTTP imports
- [ ] Every repository method returns `Result` or a `Stream` of entities, never a DTO
- [ ] `DioException` is caught in one mapper, nowhere else
- [ ] Validation failures carry field-level messages
- [ ] Use cases exist only where they orchestrate or guard a rule
- [ ] Controllers depend on interfaces through providers
- [ ] Tenant or role scoped data depends on the tenant scope provider (see `role-switching.md`)
- [ ] `test/` mirrors `lib/`, and every repository has a fake
