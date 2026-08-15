# services/integrations

Внешние интеграции через адаптеры.

```
AdPlatformAdapter
├── YandexDirectAdapter
├── MockAdPlatformAdapter
└── future: VkAdsAdapter
```

Domain-сущности Campaign / AdGroup / Target / Creative / Budget не содержат
Yandex-специфичных полей как обязательных; платформенная специфика хранится в
adapter metadata / external mapping (v0.4 §17).

Также: YandexMetricaAdapter, YandexWordstatAdapter (с quota tracking, кешем и
деградацией — v0.4 §2.4), CRMAdapter.
