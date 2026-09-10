---
id: ejari
kind: rera
title: Ejari tenancy registration
source: Dubai Land Department guidance on Ejari
source_url: https://dubailand.gov.ae/en/eservices/
status: archived, but the page does not contain the cited terms
retrieved: 2026-09-10T07:23:30+00:00 · sha256 c240398d250cdf81 · docs/sources/ejari
expect_terms: Ejari, tenancy contract, registration
lang: en
---

# Ejari tenancy registration

Ejari is the Dubai Land Department system through which tenancy contracts are registered. Every
tenancy in Dubai is required to be registered, and registration is what makes a contract
recognised for utility connections, visa processes and disputes.

## Why it matters to this project

Ejari is the reason Dubai has public rent data at all. Because tenancies are registered centrally,
the rent actually agreed on a contract becomes part of an open dataset rather than remaining
private between landlord and tenant. That is what makes a measured yield possible: the rent side of
the calculation comes from recorded contracts, not from asking prices on a portal.

## What the data does and does not contain

The registry records the contract: the property, the period and the annual rent. It does not record
the gaps between tenancies, so **vacancy cannot be measured from the open data and has to be
assumed**. YIELDMAP's vacancy assumption is stated in `config/assumptions.yaml` and is editable.

It also records rent for the specific unit under contract. YIELDMAP's yields use the median rent
for an area, property type and bedroom count rather than the rent of a particular unit, so a yield
shown for a cell describes that cell rather than any individual property.

## بالعربية: تسجيل عقود الإيجار عبر إيجاري

إيجاري هو نظام دائرة الأراضي والأملاك في دبي لتسجيل عقود الإيجار. تسجيل كل عقد إيجار في دبي إلزامي،
والتسجيل هو ما يجعل العقد معترفاً به لتوصيل الخدمات وإجراءات الإقامة والنزاعات.

إيجاري هو سبب توفّر بيانات إيجارات عامة في دبي أصلاً: لأن العقود تُسجَّل مركزياً، يصبح الإيجار المتفق
عليه فعلياً جزءاً من بيانات مفتوحة بدل أن يبقى خاصاً. وهذا ما يجعل حساب العائد المقيس ممكناً، إذ يأتي
جانب الإيجار من عقود مسجَّلة لا من أسعار معروضة على المواقع.

يسجّل النظام العقار والمدة والإيجار السنوي، لكنه لا يسجّل الفترات بين العقود، لذلك لا يمكن قياس نسبة
الشغور من البيانات المفتوحة ويجب افتراضها.

## हिन्दी में: इजारी किरायेदारी पंजीकरण

इजारी दुबई भूमि विभाग की वह प्रणाली है जिसके माध्यम से किरायेदारी अनुबंध पंजीकृत होते हैं। दुबई में हर
किरायेदारी का पंजीकरण आवश्यक है, और पंजीकरण ही अनुबंध को उपयोगिता कनेक्शन, वीज़ा प्रक्रियाओं और
विवादों के लिए मान्यता देता है।

इजारी के कारण ही दुबई में सार्वजनिक किराया डेटा उपलब्ध है। अनुबंध केंद्रीय रूप से पंजीकृत होने से वास्तविक
सहमत किराया खुले डेटासेट का हिस्सा बन जाता है, न कि मकान मालिक और किरायेदार के बीच निजी रह जाता है।
इसी से मापित प्रतिफल संभव होता है, क्योंकि किराया पक्ष दर्ज अनुबंधों से आता है, पोर्टल की माँग कीमतों से नहीं।

प्रणाली संपत्ति, अवधि और वार्षिक किराया दर्ज करती है, पर किरायेदारियों के बीच के अंतराल नहीं। इसलिए खुले
डेटा से रिक्तता मापी नहीं जा सकती और उसे मानना पड़ता है।
