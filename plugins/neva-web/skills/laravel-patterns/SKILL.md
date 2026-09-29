---
name: laravel-patterns
description: "Laravel architecture for production apps, incl. Blade, Alpine, Tailwind, RTL-first UIs: controllers, services, Eloquent, validation with specific errors, ledgers, queues, caching. Use when building or reviewing Laravel apps."
metadata:
  origin: affaan-m/ECC (MIT), adapted for Neva
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Blade/Alpine/Tailwind, RTL, identity, specific-error, ledger, and token sections are generic lessons from Neva house practice. -->

# Laravel Development Patterns

Production-grade Laravel architecture patterns for scalable, maintainable applications.

## When to Use

- Building Laravel web applications or APIs
- Structuring controllers, services, and domain logic
- Working with Eloquent models and relationships
- Designing APIs with resources and pagination
- Adding queues, events, caching, and background jobs

## How It Works

- Structure the app around clear boundaries (controllers -> services/actions -> models).
- Use explicit bindings and scoped bindings to keep routing predictable; still enforce authorization for access control.
- Favor typed models, casts, and scopes to keep domain logic consistent.
- Keep IO-heavy work in queues and cache expensive reads.
- Centralize config in `config/*` and keep environments explicit.
- New business logic means a new service or action. Never put it in controllers, models, or Blade templates.
- Server-rendered first: Blade components + Alpine for interaction + Tailwind for styling. Reach for a SPA framework only as a deliberate, recorded decision.
- Every UI works in both reading directions (RTL and LTR) or it does not ship.
- Tests run on an in-memory SQLite connection and never touch a dev database (see `laravel-tdd`).

## Examples

### Project Structure

Use a conventional Laravel layout with clear layer boundaries (HTTP, services/actions, models).

### Recommended Layout

```
app/
├── Actions/            # Single-purpose use cases
├── Console/
├── Events/
├── Exceptions/
├── Http/
│   ├── Controllers/
│   ├── Middleware/
│   ├── Requests/       # Form request validation
│   └── Resources/      # API resources
├── Jobs/
├── Models/
├── Policies/
├── Providers/
├── Services/           # Coordinating domain services
└── Support/
config/
database/
├── factories/
├── migrations/
└── seeders/
resources/
├── views/
└── lang/
routes/
├── api.php
├── web.php
└── console.php
```

### Controllers -> Services -> Actions

Keep controllers thin. Put orchestration in services and single-purpose logic in actions.

```php
final class CreateOrderAction
{
    public function __construct(private OrderRepository $orders) {}

    public function handle(CreateOrderData $data): Order
    {
        return $this->orders->create($data);
    }
}

final class OrdersController extends Controller
{
    public function __construct(private CreateOrderAction $createOrder) {}

    public function store(StoreOrderRequest $request): JsonResponse
    {
        $order = $this->createOrder->handle($request->toDto());

        return response()->json([
            'success' => true,
            'data' => OrderResource::make($order),
            'error' => null,
            'meta' => null,
        ], 201);
    }
}
```

### Routing and Controllers

Prefer route-model binding and resource controllers for clarity.

```php
use Illuminate\Support\Facades\Route;

Route::middleware('auth:sanctum')->group(function () {
    Route::apiResource('projects', ProjectController::class);
});
```

### Route Model Binding (Scoped)

Use scoped bindings to prevent cross-tenant access.

```php
Route::scopeBindings()->group(function () {
    Route::get('/accounts/{account}/projects/{project}', [ProjectController::class, 'show']);
});
```

### Nested Routes and Binding Names

- Keep prefixes and paths consistent to avoid double nesting (e.g., `conversation` vs `conversations`).
- Use a single parameter name that matches the bound model (e.g., `{conversation}` for `Conversation`).
- Prefer scoped bindings when nesting to enforce parent-child relationships.

```php
use App\Http\Controllers\Api\ConversationController;
use App\Http\Controllers\Api\MessageController;
use Illuminate\Support\Facades\Route;

Route::middleware('auth:sanctum')->prefix('conversations')->group(function () {
    Route::post('/', [ConversationController::class, 'store'])->name('conversations.store');

    Route::scopeBindings()->group(function () {
        Route::get('/{conversation}', [ConversationController::class, 'show'])
            ->name('conversations.show');

        Route::post('/{conversation}/messages', [MessageController::class, 'store'])
            ->name('conversation-messages.store');

        Route::get('/{conversation}/messages/{message}', [MessageController::class, 'show'])
            ->name('conversation-messages.show');
    });
});
```

If you want a parameter to resolve to a different model class, define explicit binding. For custom binding logic, use `Route::bind()` or implement `resolveRouteBinding()` on the model.

```php
use App\Models\AiConversation;
use Illuminate\Support\Facades\Route;

Route::model('conversation', AiConversation::class);
```

### Service Container Bindings

Bind interfaces to implementations in a service provider for clear dependency wiring.

```php
use App\Repositories\EloquentOrderRepository;
use App\Repositories\OrderRepository;
use Illuminate\Support\ServiceProvider;

final class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->app->bind(OrderRepository::class, EloquentOrderRepository::class);
    }
}
```

### Eloquent Model Patterns

### Model Configuration

```php
final class Project extends Model
{
    use HasFactory;

    protected $fillable = ['name', 'owner_id', 'status'];

    protected $casts = [
        'status' => ProjectStatus::class,
        'archived_at' => 'datetime',
    ];

    public function owner(): BelongsTo
    {
        return $this->belongsTo(User::class, 'owner_id');
    }

    public function scopeActive(Builder $query): Builder
    {
        return $query->whereNull('archived_at');
    }
}
```

### Custom Casts and Value Objects

Use enums or value objects for strict typing.

```php
use Illuminate\Database\Eloquent\Casts\Attribute;

protected $casts = [
    'status' => ProjectStatus::class,
];
```

```php
protected function budgetCents(): Attribute
{
    return Attribute::make(
        get: fn (int $value) => Money::fromCents($value),
        set: fn (Money $money) => $money->toCents(),
    );
}
```

### Eager Loading to Avoid N+1

```php
$orders = Order::query()
    ->with(['customer', 'items.product'])
    ->latest()
    ->paginate(25);
```

### Query Objects for Complex Filters

```php
final class ProjectQuery
{
    public function __construct(private Builder $query) {}

    public function ownedBy(int $userId): self
    {
        $query = clone $this->query;

        return new self($query->where('owner_id', $userId));
    }

    public function active(): self
    {
        $query = clone $this->query;

        return new self($query->whereNull('archived_at'));
    }

    public function builder(): Builder
    {
        return $this->query;
    }
}
```

### Global Scopes and Soft Deletes

Use global scopes for default filtering and `SoftDeletes` for recoverable records.
Use either a global scope or a named scope for the same filter, not both, unless you intend layered behavior.

```php
use Illuminate\Database\Eloquent\SoftDeletes;
use Illuminate\Database\Eloquent\Builder;

final class Project extends Model
{
    use SoftDeletes;

    protected static function booted(): void
    {
        static::addGlobalScope('active', function (Builder $builder): void {
            $builder->whereNull('archived_at');
        });
    }
}
```

### Query Scopes for Reusable Filters

```php
use Illuminate\Database\Eloquent\Builder;

final class Project extends Model
{
    public function scopeOwnedBy(Builder $query, int $userId): Builder
    {
        return $query->where('owner_id', $userId);
    }
}

// In service, repository etc.
$projects = Project::ownedBy($user->id)->get();
```

### Transactions for Multi-Step Updates

```php
use Illuminate\Support\Facades\DB;

DB::transaction(function (): void {
    $order->update(['status' => 'paid']);
    $order->items()->update(['paid_at' => now()]);
});
```

### Migrations

### Naming Convention

- File names use timestamps: `YYYY_MM_DD_HHMMSS_create_users_table.php`
- Migrations use anonymous classes (no named class); the filename communicates intent
- Table names are `snake_case` and plural by default

### Example Migration

```php
use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('orders', function (Blueprint $table): void {
            $table->id();
            $table->foreignId('customer_id')->constrained()->cascadeOnDelete();
            $table->string('status', 32)->index();
            $table->unsignedInteger('total_cents');
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('orders');
    }
};
```

### Form Requests and Validation

Keep validation in form requests and transform inputs to DTOs.

```php
use App\Models\Order;

final class StoreOrderRequest extends FormRequest
{
    public function authorize(): bool
    {
        return $this->user()?->can('create', Order::class) ?? false;
    }

    public function rules(): array
    {
        return [
            'customer_id' => ['required', 'integer', 'exists:customers,id'],
            'items' => ['required', 'array', 'min:1'],
            'items.*.sku' => ['required', 'string'],
            'items.*.quantity' => ['required', 'integer', 'min:1'],
        ];
    }

    public function toDto(): CreateOrderData
    {
        return new CreateOrderData(
            customerId: (int) $this->validated('customer_id'),
            items: $this->validated('items'),
        );
    }
}
```

### API Resources

Keep API responses consistent with resources and pagination.

```php
$projects = Project::query()->active()->paginate(25);

return response()->json([
    'success' => true,
    'data' => ProjectResource::collection($projects->items()),
    'error' => null,
    'meta' => [
        'page' => $projects->currentPage(),
        'per_page' => $projects->perPage(),
        'total' => $projects->total(),
    ],
]);
```

### Events, Jobs, and Queues

- Emit domain events for side effects (emails, analytics)
- Use queued jobs for slow work (reports, exports, webhooks)
- Prefer idempotent handlers with retries and backoff

### Caching

- Cache read-heavy endpoints and expensive queries
- Invalidate caches on model events (created/updated/deleted)
- Use tags when caching related data for easy invalidation

### Configuration and Environments

- Keep secrets in `.env` and config in `config/*.php`
- Use per-environment config overrides and `config:cache` in production

## Server-Rendered Frontend: Blade + Alpine + Tailwind

### Blade components are the canonical surface

Anything shown in more than one place is a Blade component under `resources/views/components/`. Every place that shows it uses the component; a new variant extends the component with a prop or slot instead of forking the markup.

```blade
{{-- resources/views/components/money.blade.php --}}
@props(['cents', 'currency'])
<bdi class="tabular-nums" dir="ltr">{{ \App\Support\Money::format($cents, $currency, app()->getLocale()) }}</bdi>
```

- Echo with `{{ }}`. Use `{!! !!}` only for HTML you sanitized, with a comment naming the sanitizer.
- Pass data in, do not query in views. No Eloquent calls inside Blade.

### Alpine for interaction

```blade
<div x-data="quantityPicker({ min: 1, max: {{ $max }} })" class="inline-flex items-center gap-2">
    <button type="button" @click="dec" :disabled="qty <= min" aria-label="{{ __('cart.decrease') }}">-</button>
    <output x-text="qty" class="tabular-nums" aria-live="polite"></output>
    <button type="button" @click="inc" :disabled="qty >= max" aria-label="{{ __('cart.increase') }}">+</button>
</div>

@push('scripts')
<script>
document.addEventListener('alpine:init', () => {
    Alpine.data('quantityPicker', ({ min, max }) => ({
        min, max, qty: min,
        inc() { if (this.qty < this.max) this.qty++ },
        dec() { if (this.qty > this.min) this.qty-- },
    }));
});
</script>
@endpush
```

- Keep `x-data` small and local; register anything non-trivial with `Alpine.data()`.
- For server round-trips without a SPA, swap server-rendered partials (Alpine `fetch`, HTMX, or Livewire, whichever the project already uses). Do not add a second one.

### Tailwind, RTL-first

- `<html lang="{{ str_replace('_', '-', app()->getLocale()) }}" dir="{{ in_array(app()->getLocale(), ['ar', 'he', 'fa', 'ur']) ? 'rtl' : 'ltr' }}">`, or better, read direction from a locale config map.
- Logical utilities only: `ms-4 me-2 ps-6 pe-3 start-0 end-0 text-start rounded-s-lg border-e`. Physical `ml-*`, `pr-*`, `left-*`, `text-right` are review findings unless the element must not mirror.
- Mirror directional icons with `rtl:-scale-x-100`. Numbers, phones, codes, and money go in `<bdi>` or `dir="ltr"`.
- Pick one digit system per product and format through one helper; never mix Arabic-Indic and Latin digits on a screen.

## Localization

- All user-facing strings go through `__()` / `@lang`. No literals in Blade or in validation messages.
- A new translation key is added to every locale file in the same change. A missing key in one locale is a bug, not a follow-up.
- Locale-prefixed routes (`/{locale}/...`) with a `SetLocale` middleware are the simplest way to make locale explicit and cacheable.
- Dates and numbers format through Carbon's locale (`->locale($locale)->isoFormat(...)`) and `NumberFormatter`, never hand-built strings.

## Validation Errors Name the Field and the Fix

Generic messages ("The form contains errors", "validation.regex") are defects. Every rule gets a specific, translated message; every field renders its own error.

```php
public function messages(): array
{
    return [
        'phone.required' => __('auth.phone_required'),       // "Enter your phone number to continue."
        'phone.regex'    => __('auth.phone_format'),         // "Phone number needs the country code, for example +44 7700 900123."
        'quantity.max'   => __('cart.quantity_max', ['max' => 10]), // "You can order up to 10. Lower the quantity."
    ];
}
```

```blade
<label for="phone">{{ __('auth.phone') }}</label>
<input id="phone" name="phone" type="tel" inputmode="tel" autocomplete="tel"
       value="{{ old('phone') }}" aria-describedby="phone-error" @error('phone') aria-invalid="true" @enderror>
@error('phone')<p id="phone-error" class="text-sm text-red-700">{{ $message }}</p>@enderror
```

A top-of-form summary, if any, lists each failing field with its message and links to it. Service-layer failures pass their specific message through ("Code expired. Request a new one.") instead of being replaced by a generic one.

## Identity: Phone-First When the Product Calls for It

For consumer products where people sign in by phone (common in markets where phone numbers outnumber active email addresses):

- Phone is the unique key. Store one canonical international format (leading `+`, digits only) in a `phone` column with a unique index. Email is nullable and never required from a customer.
- One normalizer class owns the rules (`App\Support\PhoneNormalizer`). Every entry point (signup, login, import, admin search, cashier or POS claim) calls it. Several ad-hoc `normalizePhone()` copies cause identity splits: the same person stored twice.
- Normalize only what is unambiguous (for example a national trunk prefix to the international form). Reject everything else at the boundary with a specific message per failure: wrong length, landline that cannot receive SMS, unknown operator prefix, stray characters.
- Authenticate with a one-time code sent to the phone; codes expire, attempts are counted, and the remaining attempts are shown.
- Lookups (`findByIdentifier`) search phone first. Notifications to phone-only users go by SMS or push, and degrade gracefully when neither is available.
- Staff and admin accounts can keep email as a contact field, but sign-in follows the same phone flow.

## Money, Ledgers, and Derived State

- Money is an integer in minor units plus a currency code. Never floats. Format at the edge.
- For points, credits, wallets, or stock: an append-only ledger of events is the source of truth; balances are derived (materialized or computed), never written directly.
- A reversal never deletes or edits the original event. It creates an inverse event that references it (`reverses_event_id`) and carries a required reason.
- Status earned from history (a tier, a badge, a lifetime total) is computed from what was earned, and a reversal does not silently downgrade it unless a separate, explicit action says so.
- Keep an audit log (who, what, when, from where) separate from the domain ledger for staff and admin actions.

## Tokens, Idempotency, and Guards

- Redemptions, claims, invites, and magic links use signed, single-use, time-limited tokens. Validate, consume, and mark used in one transaction.
- Anything a retry or double-click can repeat (payments, awards, webhooks) takes an idempotency key with a unique index.
- Jobs that touch money or ledgers implement `ShouldBeUnique` or dedupe on a key, and dispatch `afterCommit()` so they never see uncommitted rows.
- Multiple user types (customers, staff, partners, admins) get separate guards in `config/auth.php`, each with its own model, routes, and middleware. Never branch on a role column inside one guard to fake separation.
- Tenant-owned records are scoped by default (global scope or scoped bindings). Cross-tenant access is an explicit, logged elevation.

## Environment-Aware Validation

Strict rules that need the network (`email:rfc,dns`) run in production; local and testing use the offline variant (`email:rfc`) so fixtures work:

```php
'email' => ['nullable', app()->isProduction() ? 'email:rfc,dns' : 'email:rfc'],
```
