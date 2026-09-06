---
id: service_charges
kind: service_charge
title: Service charges and the Mollak system
source: Dubai Land Department guidance on Mollak
source_url: https://dubailand.gov.ae/mydld/mollak_service_charges/
status: unverified
retrieved: not yet archived — the ingest job could not reach the publisher
lang: en
---

# Service charges and the Mollak system

Owners of property in a jointly owned development pay an annual service charge towards the upkeep
of shared areas and facilities. In Dubai these charges are administered through Mollak, the Dubai
Land Department system for owners' association accounts, which approves and publishes per-building
figures.

## Why this is the weakest number in a yield calculation

Service charges vary enormously between buildings. A tower with a large pool deck, extensive
landscaping and concierge staffing costs far more per square metre to run than a low-rise block
with none of those, and two buildings on the same street can differ by a multiple.

YIELDMAP currently applies a single per-square-metre estimate across every property, because the
per-building figures have not been loaded. This is the largest source of error in the net yield,
and it is stated as such:

- The estimate lives in `config/assumptions.yaml` with status `estimate`.
- The interface exposes it as an editable input.
- The tests assert that changing it moves the net yield.

Loading Mollak's per-building figures would replace the estimate with a measurement, and is the
single highest-value data improvement available to this project.

## بالعربية: رسوم الخدمات ونظام مُلّاك

يدفع ملّاك العقارات في المشاريع المشتركة رسوم خدمات سنوية مقابل صيانة المناطق والمرافق المشتركة.
تُدار هذه الرسوم في دبي عبر نظام مُلّاك التابع لدائرة الأراضي والأملاك، الذي يعتمد أرقام كل مبنى
وينشرها.

تتفاوت رسوم الخدمات تفاوتاً كبيراً بين المباني: برج بمسبح واسع وتنسيق حدائق وخدمة كونسيرج يكلّف
تشغيله للمتر المربع أضعاف ما يكلّفه مبنى منخفض بلا هذه المرافق، وقد يختلف مبنيان في الشارع نفسه
بمقدار عدة أضعاف.

يطبّق هذا المشروع حالياً تقديراً واحداً للمتر المربع على كل العقارات، وهو أكبر مصدر خطأ في صافي
العائد، ومعلَّم كتقدير قابل للتعديل. تحميل أرقام مُلّاك لكل مبنى سيستبدل التقدير بقياس فعلي.

## हिन्दी में: सर्विस चार्ज और मुल्लाक प्रणाली

संयुक्त स्वामित्व वाली परियोजनाओं में संपत्ति मालिक साझा क्षेत्रों और सुविधाओं के रखरखाव के लिए वार्षिक
सर्विस चार्ज देते हैं। दुबई में यह मुल्लाक प्रणाली के माध्यम से प्रशासित होता है, जो दुबई भूमि विभाग की
प्रणाली है और प्रति-भवन आँकड़े स्वीकृत कर प्रकाशित करती है।

सर्विस चार्ज भवनों के बीच बहुत भिन्न होते हैं। बड़े पूल डेक, व्यापक भूदृश्य और कंसीयज स्टाफ वाले टावर का
प्रति वर्ग मीटर संचालन खर्च उन सुविधाओं रहित निचली इमारत से कहीं अधिक होता है, और एक ही सड़क की दो
इमारतों में कई गुना अंतर हो सकता है।

यह परियोजना फिलहाल हर संपत्ति पर एक ही प्रति वर्ग मीटर अनुमान लगाती है। यह शुद्ध प्रतिफल में त्रुटि का
सबसे बड़ा स्रोत है और संपादन योग्य अनुमान के रूप में चिह्नित है।
