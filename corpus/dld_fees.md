---
id: dld_fees
kind: law
title: Transaction fees on a Dubai property purchase
source: Dubai Land Department fee schedule
source_url: https://dubailand.gov.ae/en/services/
status: archived, but the page does not contain the cited terms
retrieved: 2026-09-11T07:21:24+00:00 · sha256 a880789e99c75a42 · docs/sources/dld_fees
expect_terms: 4%, transfer fee, registration
lang: en
---

# Transaction fees on a Dubai property purchase

Buying property in Dubai costs more than the purchase price. The additional costs fall into four
groups, and together they are the reason a gross yield overstates the return an owner actually
receives.

## Transfer fee

The Dubai Land Department charges a transfer fee on registration, calculated as a percentage of the
purchase price. It is conventionally described as being shared between buyer and seller, but in
practice the buyer customarily bears it in full. YIELDMAP assumes the buyer pays it in full, which
is the conservative assumption for a buyer's yield calculation.

## Registration and trustee fees

A registration charge applies on transfer, along with trustee office fees. These are flat amounts
rather than percentages, so they matter proportionally more on a smaller purchase.

## Mortgage registration

Where the purchase is financed, registering the mortgage attracts a further fee calculated on the
loan amount, plus an administrative charge.

## Agency commission

Buyer-side agency commission is a market convention rather than a regulated fee and is negotiable.

## How YIELDMAP uses these

All of these appear in `config/assumptions.yaml` and `config/mortgage.yaml` with a status field.
Fields marked `unverified` are shown in the interface as editable assumptions rather than as rules,
and the net yield and cash-flow projections recompute when they are changed. The values used are
widely reported figures; they are not asserted as verified until the ingest job archives the
publisher's own schedule.

## بالعربية: رسوم شراء عقار في دبي

شراء عقار في دبي يكلّف أكثر من سعر الشراء. تفرض دائرة الأراضي والأملاك رسوم نقل ملكية كنسبة مئوية
من سعر الشراء عند التسجيل. ورغم أنها توصف عادةً بأنها مقسومة بين البائع والمشتري، يتحملها المشتري
كاملةً في الممارسة العملية، وهذا هو الافتراض المستخدم هنا.

تُضاف رسوم التسجيل ورسوم مكتب الأمانة، وهي مبالغ ثابتة لا نسب مئوية، لذلك يكون أثرها النسبي أكبر
على العقارات الأرخص. وعند التمويل، يترتب رسم إضافي على تسجيل الرهن العقاري يُحتسب على مبلغ القرض.
عمولة الوسيط عرف سوقي قابل للتفاوض وليست رسماً منظّماً.

هذه القيم مُعلَّمة كغير مُتحقَّق منها وتظهر في الواجهة كافتراضات قابلة للتعديل، لا كقواعد.

## हिन्दी में: दुबई में संपत्ति खरीद पर शुल्क

दुबई में संपत्ति खरीदना खरीद मूल्य से अधिक महँगा पड़ता है। दुबई भूमि विभाग पंजीकरण पर खरीद मूल्य के
प्रतिशत के रूप में हस्तांतरण शुल्क लेता है। इसे आमतौर पर क्रेता और विक्रेता के बीच बँटा हुआ बताया जाता
है, पर व्यवहार में इसे खरीदार ही पूरा वहन करता है, और यही धारणा यहाँ प्रयुक्त है।

पंजीकरण और ट्रस्टी कार्यालय शुल्क भी लगते हैं। ये निश्चित रकम हैं, प्रतिशत नहीं, इसलिए सस्ती संपत्ति पर
इनका अनुपातिक बोझ अधिक होता है। वित्तपोषित खरीद पर बंधक पंजीकरण का अतिरिक्त शुल्क ऋण राशि पर लगता
है। एजेंसी कमीशन एक बाजार प्रथा है और परक्राम्य है।

ये मान अप्रमाणित चिह्नित हैं और इंटरफ़ेस में नियम नहीं, बल्कि संपादन योग्य धारणाओं के रूप में दिखते हैं।
