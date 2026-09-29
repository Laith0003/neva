# RTL and Arabic in Flutter

<!-- Written for Neva as an extension of the dart-flutter-patterns skill adapted from affaan-m/ECC (MIT), commit d3b8a3e. -->

Arabic-first means the Arabic layout is designed and tested, not derived. Flutter flips a lot for free once the locale is RTL; everything in this file is about the parts it does not flip, and the parts it flips that it should not.

## 1. Setup

```yaml
# pubspec.yaml
dependencies:
  flutter_localizations:
    sdk: flutter
  intl: any          # pinned by flutter_localizations
flutter:
  generate: true
  fonts:
    - family: AppSans            # one family that covers Arabic and Latin, or two with a fallback
      fonts:
        - asset: assets/fonts/AppSans-Regular.ttf
        - asset: assets/fonts/AppSans-Medium.ttf
          weight: 500
        - asset: assets/fonts/AppSans-Bold.ttf
          weight: 700
```

```yaml
# l10n.yaml
arb-dir: lib/l10n
template-arb-file: app_ar.arb      # Arabic as template when Arabic is the primary language
output-localization-file: app_localizations.dart
nullable-getter: false
```

```dart
MaterialApp.router(
  supportedLocales: AppLocalizations.supportedLocales,
  localizationsDelegates: AppLocalizations.localizationsDelegates,
  locale: ref.watch(localeProvider),          // user choice, persisted; null follows the device
  theme: buildTheme(Brightness.light),
  darkTheme: buildTheme(Brightness.dark),
  routerConfig: router,
);
```

`GlobalMaterialLocalizations`, `GlobalCupertinoLocalizations`, and `GlobalWidgetsLocalizations` must all be present (the generated `localizationsDelegates` includes them). Without `GlobalWidgetsLocalizations` the `Directionality` stays LTR even with an Arabic locale.

## 2. Directional APIs: the ban list

| Never in feature code | Use |
|---|---|
| `EdgeInsets.only(left:, right:)`, `EdgeInsets.fromLTRB` | `EdgeInsetsDirectional.only(start:, end:)`, `EdgeInsetsDirectional.fromSTEB` |
| `Alignment.centerLeft`, `topRight`, etc. | `AlignmentDirectional.centerStart`, `topEnd` |
| `Positioned(left:, right:)` | `PositionedDirectional(start:, end:)` |
| `BorderRadius.only(topLeft:)` | `BorderRadiusDirectional.only(topStart:)` |
| `Border(left: ...)` | `BorderDirectional(start: ...)` |
| `TextAlign.left`, `TextAlign.right` | `TextAlign.start`, `TextAlign.end` |
| `Row` with a hardcoded `textDirection: TextDirection.ltr` | Let it inherit; only force LTR for content that is inherently LTR (section 4) |
| `Transform.translate(offset: Offset(12, 0))` for layout | Multiply x by `Directionality.of(context) == TextDirection.rtl ? -1 : 1`, or use directional padding |

Enforce with a CI grep over `lib/features/` for `EdgeInsets.only(left`, `EdgeInsets.only(right`, `Alignment.centerLeft`, `Alignment.centerRight`, `Positioned(left`, `TextAlign.left`, `TextAlign.right`, and `fromLTRB`. Allow exceptions only with a trailing `// ltr-ok: <reason>` comment.

## 3. Icons and imagery: flip or not

Flip in RTL (directional meaning):
- back and forward arrows, chevrons in list rows, "next" and "previous"
- progress that fills along the reading direction
- icons that depict text lines or a list with bullets on one side
- send icons (paper plane pointing along reading direction)

Do NOT flip:
- media controls (play, fast forward): they follow the timeline, not reading direction
- clocks, checkmarks, plus and minus, search, settings
- brand logos, photos, and anything containing Latin text or numbers
- charts' time axis when the product shows time left to right (decide once, document it)

Material `Icons.arrow_back`, `Icons.arrow_forward`, `Icons.chevron_left/right`, and similar have `matchTextDirection: true`. Custom SVG icons do not: wrap them.

```dart
class DirectionalIcon extends StatelessWidget {
  const DirectionalIcon(this.asset, {super.key, this.size = 24});
  final String asset;
  final double size;

  @override
  Widget build(BuildContext context) {
    final rtl = Directionality.of(context) == TextDirection.rtl;
    return Transform.flip(flipX: rtl, child: SvgPicture.asset(asset, width: size, height: size));
  }
}
```

## 4. Bidi: mixed Arabic and Latin, numbers, phones

Inherently LTR content inside Arabic UI: phone numbers, card and account numbers, OTP codes, order numbers, URLs, email addresses, code, and Latin brand names. Without isolation the bidi algorithm reorders their parts (a phone like `+962 79 123 4567` renders with groups swapped).

```dart
/// Wrap inherently-LTR runs in Left-to-Right Isolate ... Pop Directional Isolate.
String ltrIsolate(String s) => '\u2066$s\u2069';

Text('${l10n.sentCodeTo} ${ltrIsolate(phone)}');

// Whole widgets that are LTR content
Directionality(
  textDirection: TextDirection.ltr,
  child: Text(orderNumber),
);
```

Input fields for LTR data (phone, OTP, email, amounts): set `textDirection: TextDirection.ltr` and `textAlign: TextAlign.end` on the `TextField` in RTL so the caret and digits behave, while the label stays Arabic and right-aligned. OTP boxes are always laid out LTR (the first digit on the left), in every locale.

## 5. Digits and number formatting

Decide per product, once:
- Western digits (0 to 9) in Arabic UI: common in the Levant and Gulf fintech, and what most users type on their keyboard.
- Arabic-Indic digits: common in Egypt and formal contexts.

Never mix both on one screen. Format through `intl`, never by string concatenation:

```dart
final money = NumberFormat.currency(locale: 'ar_JO', symbol: 'JOD', decimalDigits: 3);
final text = money.format(12.5);
```

Which digits `intl` emits depends on the locale's number symbols (`ZERO_DIGIT`), and it differs between `ar` and its regional variants. Do not guess: assert it in a unit test. To force one system regardless of locale, format then map the digits with a tested helper. Always parse user input after mapping Arabic-Indic (U+0660 to U+0669) and Extended Arabic-Indic (U+06F0 to U+06F9) digits to ASCII, because users will type both.

```dart
String toAsciiDigits(String s) => s.replaceAllMapped(
  RegExp('[\u0660-\u0669\u06F0-\u06F9]'),
  (m) {
    final c = m[0]!.codeUnitAt(0);
    return String.fromCharCode(0x30 + (c >= 0x06F0 ? c - 0x06F0 : c - 0x0660));
  },
);

String toArabicIndicDigits(String s) =>
    s.replaceAllMapped(RegExp('[0-9]'), (m) => String.fromCharCode(0x0660 + m[0]!.codeUnitAt(0) - 0x30));
```

Currency: place the symbol by locale rules via `NumberFormat`, not by hand. Percent: `NumberFormat.percentPattern(locale)`.

## 6. Typography

- Bundle an Arabic-capable family with real weights (Regular, Medium, Bold at minimum). Do not rely on the platform fallback: it differs between iOS and Android and between Android vendors, and it breaks goldens.
- Arabic glyphs sit taller with ascenders and descenders: set `height` (line height) in the `TextTheme` around 1.4 to 1.6 for body text, lower for large display text. Tune once in the theme, never per widget.
- Never set `letterSpacing` on Arabic text. Tracking breaks the cursive joins. If the Latin design uses tracking, apply it only in the Latin text theme.
- No italics for Arabic. Emphasis is weight or color.
- Truncation: `TextOverflow.ellipsis` works, but check it in RTL goldens: the ellipsis lands on the left.
- Minimum body size is larger than for Latin at the same legibility: start at 15 to 16 logical pixels for body.

```dart
TextTheme arabicTextTheme(TextTheme base) => base.apply(fontFamily: 'AppSans').copyWith(
  bodyLarge: base.bodyLarge?.copyWith(height: 1.5, letterSpacing: 0),
  bodyMedium: base.bodyMedium?.copyWith(height: 1.5, letterSpacing: 0),
  titleLarge: base.titleLarge?.copyWith(height: 1.3, letterSpacing: 0),
);
```

## 7. ARB and plurals

Arabic has six plural categories. Supply all of them, or counts like 2 and 11 read wrong.

```json
{
  "itemsCount": "{count, plural, =0{لا توجد عناصر} =1{عنصر واحد} =2{عنصران} few{{count} عناصر} many{{count} عنصرًا} other{{count} عنصر}}",
  "@itemsCount": {
    "description": "Number of items in the cart badge and summary",
    "placeholders": { "count": { "type": "int", "format": "decimalPattern" } }
  }
}
```

- Every key has a `description` for translators.
- Gendered strings use `select` on a gender placeholder.
- No concatenation of translated fragments: word order differs.
- Errors are specific per field and say the fix ("رقم الهاتف ناقص رقم، أدخل 8 أرقام بعد 07"), never a generic failure message.

## 8. Layout checks that only fail in RTL

- Swipe actions (`Dismissible`, slidable rows): the "start" side is on the right in RTL. Map actions by meaning, not by physical side.
- Horizontal `ListView` and `PageView` scroll direction flips automatically; hardcoded initial offsets do not.
- Carousels with page indicators: the first page is on the right.
- Charts: axis labels, legends, and tooltips positioned by coordinates need explicit handling.
- Hero and slide transitions: `SlideTransition` offsets are physical. Use `Offset(isRtl ? -1 : 1, 0)` or a directional page transition.
- `Stack` children positioned with physical offsets.
- Bottom sheets and dialogs are fine; custom drawers opened from "the left" are not. `Scaffold.drawer` flips; custom panels do not.

## 9. Testing

- Every screen golden is recorded twice: `en` LTR and `ar` RTL (see `widget-and-golden-tests.md`).
- A widget test that pumps under `Locale('ar')` asserts `Directionality.of(context) == TextDirection.rtl` at the screen root: this catches a missing `GlobalWidgetsLocalizations`.
- A unit test for `toAsciiDigits` with Arabic-Indic and Extended Arabic-Indic inputs.
- A unit test that every ARB key present in the template exists in every other locale file (or rely on `gen-l10n` `untranslated-messages-file` and fail CI when it is non-empty).

## 10. Checklist

- [ ] Localization delegates include Material, Cupertino, and Widgets
- [ ] No physical left/right APIs in feature code (CI grep passes)
- [ ] Custom directional icons flip, media and brand icons do not
- [ ] Phones, codes, IDs, URLs isolated as LTR in text and inputs
- [ ] One digit system per product, input normalized to ASCII before parsing
- [ ] Arabic font bundled with real weights, line height set in the theme, zero letter spacing
- [ ] All six Arabic plural forms present
- [ ] RTL golden exists for every screen
