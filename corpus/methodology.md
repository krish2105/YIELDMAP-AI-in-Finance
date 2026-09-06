---
id: methodology
kind: community
title: How YIELDMAP computes what it shows
source: This project
source_url: https://github.com/krish2105/YIELDMAP-AI-in-Finance
status: verified
retrieved: written as part of the project
lang: en
---

# How YIELDMAP computes what it shows

## Valuation

A gradient-boosted regressor predicts log price per square metre from area, property type, bedroom
count, floor area, off-plan status and time. It is trained on everything before the most recent
twelve months and scored on those twelve months, so it is never tested on data it has seen.
Predictions are transformed back from log space with Duan's smearing correction, without which they
would be biased low. Accuracy is reported against two references: the median price per square metre
for the same area, type and bedroom count, and an estimate of the data's own irreducible noise.

## Price index

A repeat-sales index compares each property against itself, so changes in the mix of what sold do
not appear as price movement. The estimator is Bailey-Muth-Nourse weighted least squares on period
dummies, weighted by inverse holding period. It is published only across a connected set of
periods, because the relative level of two period chains that share no repeat sale is not
identified by the data.

## Yield

Gross yield is the median annual Ejari rent for a cell divided by the median sale price for the
same cell over the same window. Net yield takes rent after vacancy, subtracts the service charge,
management fee, maintenance and the purchase costs amortised over an assumed holding period, and
divides by the full acquisition cost including fees. Every input is editable.

## Risk

A weighted blend of off-plan exposure, developer concentration, price volatility, illiquidity and
anomaly density, each scaled to a bounded range and clipped rather than extrapolated. The
components are always published alongside the total.

## Anomalies

Three independent signals: an isolation forest on price residuals against the area and type norm, a
rapid-resale rule for properties changing hands within ninety days, and a round-number rule for
prices landing exactly on large round figures. Every flag names the rule that fired.

## Sample size and confidence

Every figure carries the number of observations behind it. Cells below the minimum are not
published as numbers at all; they are shown as insufficient data. A yield built from two hundred
sales and three tenancies is a three-observation figure, and is treated as one.

## بالعربية: كيف يحسب YIELDMAP ما يعرضه

التقييم: نموذج تعزيز تدرّجي يتنبأ بلوغاريتم سعر المتر المربع من المنطقة ونوع العقار وعدد الغرف
والمساحة وحالة البيع على الخارطة والزمن. يُدرَّب على ما قبل آخر اثني عشر شهراً ويُختبر عليها، فلا
يُختبر على بيانات رآها.

مؤشر الأسعار: مؤشر إعادة البيع يقارن كل عقار بنفسه، فلا يظهر تغيّر تركيبة المبيعات كتغيّر في الأسعار.

العائد: العائد الإجمالي هو وسيط الإيجار السنوي المسجَّل مقسوماً على وسيط سعر البيع للفئة نفسها.
العائد الصافي يطرح الشغور ورسوم الخدمات وإدارة العقار والصيانة وتكاليف الشراء موزّعة على مدة
الاحتفاظ، ويقسم على التكلفة الكاملة للاستحواذ شاملة الرسوم.

المخاطر: مزيج مرجّح من التعرّض للبيع على الخارطة وتركّز المطوّرين وتقلّب الأسعار وضعف السيولة وكثافة
الحالات الشاذة. كل رقم يحمل عدد الملاحظات خلفه، والفئات الأقل من الحد الأدنى لا تُنشر كأرقام.

## हिन्दी में: YIELDMAP कैसे गणना करता है

मूल्यांकन: एक ग्रेडिएंट-बूस्टेड मॉडल क्षेत्र, संपत्ति प्रकार, शयनकक्ष संख्या, क्षेत्रफल, ऑफ-प्लान स्थिति और
समय से प्रति वर्ग मीटर मूल्य के लघुगणक का अनुमान लगाता है। यह पिछले बारह महीनों से पहले के आँकड़ों पर
प्रशिक्षित और उन बारह महीनों पर परखा जाता है, इसलिए इसे देखे हुए डेटा पर कभी नहीं परखा जाता।

मूल्य सूचकांक: पुनर्विक्रय सूचकांक हर संपत्ति की तुलना स्वयं से करता है, जिससे बिकने वाली संपत्तियों की
संरचना में बदलाव मूल्य परिवर्तन जैसा नहीं दिखता।

प्रतिफल: सकल प्रतिफल उसी श्रेणी के लिए दर्ज वार्षिक किराये का माध्य भाग बिक्री मूल्य के माध्य से। शुद्ध
प्रतिफल रिक्तता के बाद किराये से सर्विस चार्ज, प्रबंधन शुल्क, रखरखाव और अवधि पर फैली खरीद लागत घटाकर
शुल्क सहित पूर्ण अधिग्रहण लागत से भाग देता है।

जोखिम: ऑफ-प्लान जोखिम, डेवलपर संकेंद्रण, मूल्य अस्थिरता, तरलता की कमी और असामान्यता घनत्व का भारित
मिश्रण। हर आँकड़ा अपने पीछे की प्रेक्षण संख्या साथ रखता है।
