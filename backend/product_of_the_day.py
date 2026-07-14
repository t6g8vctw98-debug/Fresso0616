"""Product of the Day — curated, nutritionist-vetted data.

A self-contained dataset + helpers for the "Product of the Day" home-screen
feature. No external services or API keys required — everything works offline
and is deterministic so every client sees the same product on a given day.

Design notes
------------
* Each product has a stable `id`, an emoji, localized name + health benefits
  (5 languages: ru/en/it/es/fr), and three recipe links: a main dish, a salad
  and a breakfast.
* Recipe links point to *category/search* pages on a whitelist of trusted,
  nutrition-reviewed publishers (Harvard Nutrition Source, EatingWell, BBC Good
  Food, the Academy of Nutrition and Dietetics, American Heart Association).
  Using their on-site search keeps links durable (deep-links rot over time)
  while guaranteeing results only ever come from a vetted source.
* Rotation is deterministic by day-of-year, so the product changes at local
  midnight and is identical for everyone, with no storage required.

Public API
----------
    get_product_of_the_day(lang="en", day=None) -> dict
    get_all_products(lang="en") -> list[dict]
    TRUSTED_SOURCES -> list[dict]   # for an "about our sources" surface
"""
from __future__ import annotations

import datetime
from typing import Optional
from urllib.parse import quote_plus

# ──────────────────────────────────────────────────────────────────────────────
# Trusted, nutrition-reviewed recipe publishers (whitelist).
# Every recipe link in this module resolves to one of these domains.
# ──────────────────────────────────────────────────────────────────────────────
TRUSTED_SOURCES = [
    {
        "id": "harvard",
        "name": "Harvard Nutrition Source",
        "domain": "nutritionsource.hsph.harvard.edu",
        "search": "https://nutritionsource.hsph.harvard.edu/?s={q}",
        "note": "Science-based, dietitian-developed recipes from Harvard T.H. Chan School of Public Health.",
    },
    {
        "id": "eatingwell",
        "name": "EatingWell",
        "domain": "eatingwell.com",
        "search": "https://www.eatingwell.com/search?q={q}",
        "note": "Registered-dietitian-reviewed recipes with full nutrition analysis.",
    },
    {
        "id": "bbcgoodfood",
        "name": "BBC Good Food",
        "domain": "bbcgoodfood.com",
        "search": "https://www.bbcgoodfood.com/search?q={q}",
        "note": "Triple-tested recipes with nutritionist oversight.",
    },
    {
        "id": "heart",
        "name": "American Heart Association",
        "domain": "recipes.heart.org",
        "search": "https://recipes.heart.org/en/search?term={q}",
        "note": "Heart-healthy recipes vetted by the American Heart Association.",
    },
]

_SOURCE_BY_ID = {s["id"]: s for s in TRUSTED_SOURCES}


def _link(source_id: str, query: str) -> dict:
    """Build a durable recipe link on a trusted source for `query`."""
    src = _SOURCE_BY_ID[source_id]
    url = src["search"].format(q=quote_plus(query))
    return {"url": url, "source": src["name"], "domain": src["domain"]}


# ──────────────────────────────────────────────────────────────────────────────
# Curated product dataset.
#
# Each product:
#   id, emoji,
#   name:     {lang: str},
#   benefits: {lang: [str, ...]},   # 3-4 nutritionist-vetted bullet points
#   recipes:  {main, salad, breakfast}  -> {source_id, query}
#
# Recipe `query` strings are English (the trusted sources are English-language);
# the dish *type* is localized in the API layer, not here.
# ──────────────────────────────────────────────────────────────────────────────

PRODUCTS = [
    {
        "id": "spinach",
        "emoji": "\U0001F96C",
        "name": {"ru": "Шпинат", "en": "Spinach", "it": "Spinaci", "es": "Espinaca", "fr": "Épinard"},
        "benefits": {
            "ru": [
                "Богат железом и фолиевой кислотой — поддерживает кроветворение.",
                "Источник витамина K для здоровья костей и свёртываемости крови.",
                "Лютеин и зеаксантин защищают зрение.",
                "Много клетчатки при минимуме калорий.",
            ],
            "en": [
                "Rich in iron and folate to support healthy blood.",
                "A source of vitamin K for bone health and clotting.",
                "Lutein and zeaxanthin help protect eyesight.",
                "High in fiber with very few calories.",
            ],
            "it": [
                "Ricco di ferro e folati per un sangue sano.",
                "Fonte di vitamina K per ossa e coagulazione.",
                "Luteina e zeaxantina proteggono la vista.",
                "Tanta fibra con pochissime calorie.",
            ],
            "es": [
                "Rico en hierro y folato para una sangre saludable.",
                "Fuente de vitamina K para los huesos y la coagulación.",
                "La luteína y la zeaxantina protegen la vista.",
                "Mucha fibra con muy pocas calorías.",
            ],
            "fr": [
                "Riche en fer et en folates pour un sang sain.",
                "Source de vitamine K pour les os et la coagulation.",
                "La lutéine et la zéaxanthine protègent la vue.",
                "Beaucoup de fibres pour très peu de calories.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "spinach dinner"},
            "salad": {"source_id": "eatingwell", "query": "spinach salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "spinach breakfast eggs"},
        },
    },
    {
        "id": "blueberry",
        "emoji": "\U0001FAD0",
        "name": {"ru": "Черника", "en": "Blueberry", "it": "Mirtillo", "es": "Arándano", "fr": "Myrtille"},
        "benefits": {
            "ru": [
                "Один из самых богатых антиоксидантами продуктов.",
                "Антоцианы поддерживают память и работу мозга.",
                "Помогает контролировать уровень сахара в крови.",
                "Источник витамина C и марганца.",
            ],
            "en": [
                "Among the most antioxidant-rich foods.",
                "Anthocyanins support memory and brain health.",
                "May help with blood-sugar control.",
                "A source of vitamin C and manganese.",
            ],
            "it": [
                "Tra gli alimenti più ricchi di antiossidanti.",
                "Le antocianine sostengono memoria e cervello.",
                "Possono aiutare a controllare la glicemia.",
                "Fonte di vitamina C e manganese.",
            ],
            "es": [
                "De los alimentos más ricos en antioxidantes.",
                "Las antocianinas favorecen la memoria y el cerebro.",
                "Pueden ayudar a controlar el azúcar en sangre.",
                "Fuente de vitamina C y manganeso.",
            ],
            "fr": [
                "Parmi les aliments les plus riches en antioxydants.",
                "Les anthocyanes soutiennent la mémoire et le cerveau.",
                "Peut aider à réguler la glycémie.",
                "Source de vitamine C et de manganèse.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "blueberry chicken"},
            "salad": {"source_id": "eatingwell", "query": "blueberry salad"},
            "breakfast": {"source_id": "harvard", "query": "blueberry"},
        },
    },
    {
        "id": "salmon",
        "emoji": "\U0001F41F",
        "name": {"ru": "Лосось", "en": "Salmon", "it": "Salmone", "es": "Salmón", "fr": "Saumon"},
        "benefits": {
            "ru": [
                "Богат омега-3 жирными кислотами для сердца и мозга.",
                "Высококачественный белок для мышц.",
                "Один из немногих пищевых источников витамина D.",
                "Содержит селен и витамины группы B.",
            ],
            "en": [
                "Rich in omega-3 fatty acids for heart and brain.",
                "High-quality protein for muscles.",
                "One of the few food sources of vitamin D.",
                "Provides selenium and B vitamins.",
            ],
            "it": [
                "Ricco di omega-3 per cuore e cervello.",
                "Proteine di alta qualità per i muscoli.",
                "Una delle poche fonti alimentari di vitamina D.",
                "Contiene selenio e vitamine del gruppo B.",
            ],
            "es": [
                "Rico en omega-3 para el corazón y el cerebro.",
                "Proteína de alta calidad para los músculos.",
                "Una de las pocas fuentes de vitamina D.",
                "Aporta selenio y vitaminas del grupo B.",
            ],
            "fr": [
                "Riche en oméga-3 pour le cœur et le cerveau.",
                "Protéines de haute qualité pour les muscles.",
                "Une des rares sources alimentaires de vitamine D.",
                "Apporte du sélénium et des vitamines B.",
            ],
        },
        "recipes": {
            "main": {"source_id": "heart", "query": "salmon"},
            "salad": {"source_id": "eatingwell", "query": "salmon salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "smoked salmon breakfast"},
        },
    },
    {
        "id": "oats",
        "emoji": "\U0001F33E",
        "name": {"ru": "Овсянка", "en": "Oats", "it": "Avena", "es": "Avena", "fr": "Avoine"},
        "benefits": {
            "ru": [
                "Бета-глюкан снижает уровень холестерина.",
                "Медленные углеводы дают долгую сытость.",
                "Поддерживает здоровье кишечника клетчаткой.",
                "Источник магния и железа.",
            ],
            "en": [
                "Beta-glucan helps lower cholesterol.",
                "Slow carbs keep you full longer.",
                "Fiber supports gut health.",
                "A source of magnesium and iron.",
            ],
            "it": [
                "Il beta-glucano aiuta ad abbassare il colesterolo.",
                "Carboidrati lenti per una sazietà duratura.",
                "La fibra sostiene la salute intestinale.",
                "Fonte di magnesio e ferro.",
            ],
            "es": [
                "El betaglucano ayuda a reducir el colesterol.",
                "Carbohidratos lentos que sacian por más tiempo.",
                "La fibra favorece la salud intestinal.",
                "Fuente de magnesio y hierro.",
            ],
            "fr": [
                "Le bêta-glucane aide à réduire le cholestérol.",
                "Des glucides lents pour une satiété durable.",
                "Les fibres soutiennent la santé intestinale.",
                "Source de magnésium et de fer.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "savoury oats"},
            "salad": {"source_id": "eatingwell", "query": "oat grain salad"},
            "breakfast": {"source_id": "harvard", "query": "oatmeal"},
        },
    },
    {
        "id": "avocado",
        "emoji": "\U0001F951",
        "name": {"ru": "Авокадо", "en": "Avocado", "it": "Avocado", "es": "Aguacate", "fr": "Avocat"},
        "benefits": {
            "ru": [
                "Полезные мононенасыщенные жиры для сердца.",
                "Богат калием — больше, чем в банане.",
                "Клетчатка улучшает пищеварение.",
                "Помогает усваивать жирорастворимые витамины.",
            ],
            "en": [
                "Heart-healthy monounsaturated fats.",
                "Rich in potassium — more than a banana.",
                "Fiber aids digestion.",
                "Helps absorb fat-soluble vitamins.",
            ],
            "it": [
                "Grassi monoinsaturi amici del cuore.",
                "Ricco di potassio, più di una banana.",
                "La fibra favorisce la digestione.",
                "Aiuta ad assorbire le vitamine liposolubili.",
            ],
            "es": [
                "Grasas monoinsaturadas buenas para el corazón.",
                "Rico en potasio, más que un plátano.",
                "La fibra ayuda a la digestión.",
                "Ayuda a absorber vitaminas liposolubles.",
            ],
            "fr": [
                "Des graisses mono-insaturées bonnes pour le cœur.",
                "Riche en potassium, plus qu'une banane.",
                "Les fibres facilitent la digestion.",
                "Aide à absorber les vitamines liposolubles.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "avocado dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "avocado salad"},
            "breakfast": {"source_id": "eatingwell", "query": "avocado toast"},
        },
    },
    {
        "id": "broccoli",
        "emoji": "\U0001F966",
        "name": {"ru": "Брокколи", "en": "Broccoli", "it": "Broccoli", "es": "Brócoli", "fr": "Brocoli"},
        "benefits": {
            "ru": [
                "Сульфорафан обладает противовоспалительными свойствами.",
                "Очень богат витамином C и витамином K.",
                "Источник растительного белка и клетчатки.",
                "Поддерживает естественную детоксикацию печени.",
            ],
            "en": [
                "Sulforaphane has anti-inflammatory properties.",
                "Very high in vitamin C and vitamin K.",
                "A source of plant protein and fiber.",
                "Supports the liver's natural detox pathways.",
            ],
            "it": [
                "Il sulforafano ha proprietà antinfiammatorie.",
                "Ricchissimo di vitamina C e vitamina K.",
                "Fonte di proteine vegetali e fibra.",
                "Sostiene la naturale detossificazione del fegato.",
            ],
            "es": [
                "El sulforafano tiene propiedades antiinflamatorias.",
                "Muy rico en vitamina C y vitamina K.",
                "Fuente de proteína vegetal y fibra.",
                "Apoya la desintoxicación natural del hígado.",
            ],
            "fr": [
                "Le sulforaphane a des propriétés anti-inflammatoires.",
                "Très riche en vitamine C et vitamine K.",
                "Source de protéines végétales et de fibres.",
                "Soutient la détoxification naturelle du foie.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "broccoli dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "broccoli salad"},
            "breakfast": {"source_id": "eatingwell", "query": "broccoli egg breakfast"},
        },
    },
    {
        "id": "egg",
        "emoji": "\U0001F95A",
        "name": {"ru": "Яйца", "en": "Eggs", "it": "Uova", "es": "Huevos", "fr": "Œufs"},
        "benefits": {
            "ru": [
                "Полноценный белок со всеми аминокислотами.",
                "Холин важен для мозга и памяти.",
                "Лютеин и зеаксантин полезны для глаз.",
                "Доступный источник витамина D и B12.",
            ],
            "en": [
                "Complete protein with all amino acids.",
                "Choline supports brain and memory.",
                "Lutein and zeaxanthin benefit the eyes.",
                "An affordable source of vitamin D and B12.",
            ],
            "it": [
                "Proteina completa con tutti gli aminoacidi.",
                "La colina sostiene cervello e memoria.",
                "Luteina e zeaxantina fanno bene agli occhi.",
                "Fonte economica di vitamina D e B12.",
            ],
            "es": [
                "Proteína completa con todos los aminoácidos.",
                "La colina apoya el cerebro y la memoria.",
                "La luteína y zeaxantina benefician los ojos.",
                "Fuente económica de vitamina D y B12.",
            ],
            "fr": [
                "Protéine complète avec tous les acides aminés.",
                "La choline soutient le cerveau et la mémoire.",
                "La lutéine et la zéaxanthine sont bonnes pour les yeux.",
                "Source abordable de vitamine D et B12.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "egg dinner"},
            "salad": {"source_id": "eatingwell", "query": "egg salad"},
            "breakfast": {"source_id": "harvard", "query": "eggs"},
        },
    },
    {
        "id": "lentils",
        "emoji": "\U0001FAD8",
        "name": {"ru": "Чечевица", "en": "Lentils", "it": "Lenticchie", "es": "Lentejas", "fr": "Lentilles"},
        "benefits": {
            "ru": [
                "Отличный источник растительного белка.",
                "Много клетчатки для стабильного сахара в крови.",
                "Богата фолиевой кислотой и железом.",
                "Поддерживает здоровую микрофлору кишечника.",
            ],
            "en": [
                "An excellent source of plant protein.",
                "High fiber for steady blood sugar.",
                "Rich in folate and iron.",
                "Supports a healthy gut microbiome.",
            ],
            "it": [
                "Ottima fonte di proteine vegetali.",
                "Tanta fibra per una glicemia stabile.",
                "Ricche di folati e ferro.",
                "Sostengono un microbiota intestinale sano.",
            ],
            "es": [
                "Excelente fuente de proteína vegetal.",
                "Mucha fibra para un azúcar en sangre estable.",
                "Ricas en folato y hierro.",
                "Apoyan una microbiota intestinal sana.",
            ],
            "fr": [
                "Excellente source de protéines végétales.",
                "Riches en fibres pour une glycémie stable.",
                "Riches en folates et en fer.",
                "Soutiennent un microbiote intestinal sain.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "lentil curry"},
            "salad": {"source_id": "eatingwell", "query": "lentil salad"},
            "breakfast": {"source_id": "eatingwell", "query": "savory lentil breakfast"},
        },
    },
    {
        "id": "greek_yogurt",
        "emoji": "\U0001F963",
        "name": {"ru": "Греческий йогурт", "en": "Greek Yogurt", "it": "Yogurt greco", "es": "Yogur griego", "fr": "Yaourt grec"},
        "benefits": {
            "ru": [
                "Вдвое больше белка, чем в обычном йогурте.",
                "Пробиотики поддерживают пищеварение.",
                "Богат кальцием для костей.",
                "Помогает дольше сохранять чувство сытости.",
            ],
            "en": [
                "Twice the protein of regular yogurt.",
                "Probiotics support digestion.",
                "Rich in calcium for bones.",
                "Helps you feel full longer.",
            ],
            "it": [
                "Il doppio delle proteine dello yogurt normale.",
                "I probiotici sostengono la digestione.",
                "Ricco di calcio per le ossa.",
                "Aiuta a sentirsi sazi più a lungo.",
            ],
            "es": [
                "El doble de proteína que el yogur normal.",
                "Los probióticos apoyan la digestión.",
                "Rico en calcio para los huesos.",
                "Ayuda a sentirse lleno por más tiempo.",
            ],
            "fr": [
                "Deux fois plus de protéines qu'un yaourt classique.",
                "Les probiotiques soutiennent la digestion.",
                "Riche en calcium pour les os.",
                "Aide à se sentir rassasié plus longtemps.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "greek yogurt chicken"},
            "salad": {"source_id": "eatingwell", "query": "yogurt dressing salad"},
            "breakfast": {"source_id": "eatingwell", "query": "greek yogurt breakfast"},
        },
    },
    {
        "id": "sweet_potato",
        "emoji": "\U0001F360",
        "name": {"ru": "Батат", "en": "Sweet Potato", "it": "Patata dolce", "es": "Batata", "fr": "Patate douce"},
        "benefits": {
            "ru": [
                "Бета-каротин превращается в витамин A.",
                "Сложные углеводы для устойчивой энергии.",
                "Богат клетчаткой и калием.",
                "Имеет низкий гликемический индекс.",
            ],
            "en": [
                "Beta-carotene converts to vitamin A.",
                "Complex carbs for steady energy.",
                "Rich in fiber and potassium.",
                "Has a low glycemic index.",
            ],
            "it": [
                "Il beta-carotene si trasforma in vitamina A.",
                "Carboidrati complessi per energia costante.",
                "Ricca di fibra e potassio.",
                "Ha un basso indice glicemico.",
            ],
            "es": [
                "El betacaroteno se convierte en vitamina A.",
                "Carbohidratos complejos para energía estable.",
                "Rica en fibra y potasio.",
                "Tiene un índice glucémico bajo.",
            ],
            "fr": [
                "Le bêta-carotène se transforme en vitamine A.",
                "Glucides complexes pour une énergie stable.",
                "Riche en fibres et en potassium.",
                "Possède un faible index glycémique.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "sweet potato dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "sweet potato salad"},
            "breakfast": {"source_id": "eatingwell", "query": "sweet potato breakfast"},
        },
    },
    {
        "id": "walnuts",
        "emoji": "\U0001F330",
        "name": {"ru": "Грецкий орех", "en": "Walnuts", "it": "Noci", "es": "Nueces", "fr": "Noix"},
        "benefits": {
            "ru": [
                "Единственный орех, богатый растительными омега-3 (ALA).",
                "Поддерживает здоровье сердца и сосудов.",
                "Антиоксиданты защищают клетки.",
                "Полезные жиры и белок дают сытость.",
            ],
            "en": [
                "The only nut rich in plant omega-3 (ALA).",
                "Supports heart and vascular health.",
                "Antioxidants help protect cells.",
                "Healthy fats and protein keep you full.",
            ],
            "it": [
                "L'unica frutta secca ricca di omega-3 vegetali (ALA).",
                "Sostiene la salute di cuore e vasi.",
                "Gli antiossidanti proteggono le cellule.",
                "Grassi sani e proteine saziano.",
            ],
            "es": [
                "El único fruto seco rico en omega-3 vegetal (ALA).",
                "Apoya la salud del corazón y los vasos.",
                "Los antioxidantes protegen las células.",
                "Grasas sanas y proteína que sacian.",
            ],
            "fr": [
                "Le seul fruit à coque riche en oméga-3 végétal (ALA).",
                "Soutient la santé du cœur et des vaisseaux.",
                "Les antioxydants protègent les cellules.",
                "De bons gras et des protéines rassasiants.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "walnut crusted dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "walnut salad"},
            "breakfast": {"source_id": "harvard", "query": "walnut"},
        },
    },
    {
        "id": "tomato",
        "emoji": "\U0001F345",
        "name": {"ru": "Помидор", "en": "Tomato", "it": "Pomodoro", "es": "Tomate", "fr": "Tomate"},
        "benefits": {
            "ru": [
                "Ликопин — мощный антиоксидант для сердца.",
                "Богат витамином C и калием.",
                "Низкокалорийный и увлажняющий.",
                "Поддерживает здоровье кожи.",
            ],
            "en": [
                "Lycopene is a powerful antioxidant for the heart.",
                "Rich in vitamin C and potassium.",
                "Low in calories and hydrating.",
                "Supports healthy skin.",
            ],
            "it": [
                "Il licopene è un potente antiossidante per il cuore.",
                "Ricco di vitamina C e potassio.",
                "Poche calorie e idratante.",
                "Sostiene la salute della pelle.",
            ],
            "es": [
                "El licopeno es un potente antioxidante para el corazón.",
                "Rico en vitamina C y potasio.",
                "Bajo en calorías e hidratante.",
                "Apoya una piel saludable.",
            ],
            "fr": [
                "Le lycopène est un puissant antioxydant pour le cœur.",
                "Riche en vitamine C et en potassium.",
                "Peu calorique et hydratante.",
                "Soutient la santé de la peau.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "tomato pasta"},
            "salad": {"source_id": "eatingwell", "query": "tomato salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "tomato breakfast eggs"},
        },
    },
    {
        "id": "quinoa",
        "emoji": "\U0001F35A",
        "name": {"ru": "Киноа", "en": "Quinoa", "it": "Quinoa", "es": "Quinoa", "fr": "Quinoa"},
        "benefits": {
            "ru": [
                "Полноценный растительный белок со всеми аминокислотами.",
                "Не содержит глютена.",
                "Богата магнием и железом.",
                "Клетчатка поддерживает пищеварение.",
            ],
            "en": [
                "Complete plant protein with all amino acids.",
                "Naturally gluten-free.",
                "Rich in magnesium and iron.",
                "Fiber supports digestion.",
            ],
            "it": [
                "Proteina vegetale completa con tutti gli aminoacidi.",
                "Naturalmente senza glutine.",
                "Ricca di magnesio e ferro.",
                "La fibra sostiene la digestione.",
            ],
            "es": [
                "Proteína vegetal completa con todos los aminoácidos.",
                "Naturalmente sin gluten.",
                "Rica en magnesio y hierro.",
                "La fibra apoya la digestión.",
            ],
            "fr": [
                "Protéine végétale complète avec tous les acides aminés.",
                "Naturellement sans gluten.",
                "Riche en magnésium et en fer.",
                "Les fibres soutiennent la digestion.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "quinoa dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "quinoa salad"},
            "breakfast": {"source_id": "eatingwell", "query": "quinoa breakfast bowl"},
        },
    },
    {
        "id": "kale",
        "emoji": "\U0001F96C",
        "name": {"ru": "Кале", "en": "Kale", "it": "Cavolo riccio", "es": "Col rizada", "fr": "Chou kale"},
        "benefits": {
            "ru": [
                "Очень высокое содержание витаминов A, C и K.",
                "Антиоксиданты борются с воспалением.",
                "Кальций и клетчатка при низкой калорийности.",
                "Поддерживает здоровье глаз.",
            ],
            "en": [
                "Very high in vitamins A, C and K.",
                "Antioxidants fight inflammation.",
                "Calcium and fiber with few calories.",
                "Supports eye health.",
            ],
            "it": [
                "Altissimo contenuto di vitamine A, C e K.",
                "Gli antiossidanti combattono l'infiammazione.",
                "Calcio e fibra con poche calorie.",
                "Sostiene la salute degli occhi.",
            ],
            "es": [
                "Muy alto en vitaminas A, C y K.",
                "Los antioxidantes combaten la inflamación.",
                "Calcio y fibra con pocas calorías.",
                "Apoya la salud ocular.",
            ],
            "fr": [
                "Très riche en vitamines A, C et K.",
                "Les antioxydants combattent l'inflammation.",
                "Calcium et fibres pour peu de calories.",
                "Soutient la santé des yeux.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "kale dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "kale salad"},
            "breakfast": {"source_id": "eatingwell", "query": "kale egg breakfast"},
        },
    },
    {
        "id": "chickpeas",
        "emoji": "\U0001FAD8",
        "name": {"ru": "Нут", "en": "Chickpeas", "it": "Ceci", "es": "Garbanzos", "fr": "Pois chiches"},
        "benefits": {
            "ru": [
                "Растительный белок и клетчатка в одном продукте.",
                "Помогает контролировать аппетит и сахар.",
                "Источник фолиевой кислоты и железа.",
                "Поддерживает здоровье кишечника.",
            ],
            "en": [
                "Plant protein and fiber in one food.",
                "Helps control appetite and blood sugar.",
                "A source of folate and iron.",
                "Supports gut health.",
            ],
            "it": [
                "Proteine vegetali e fibra in un solo alimento.",
                "Aiutano a controllare appetito e glicemia.",
                "Fonte di folati e ferro.",
                "Sostengono la salute intestinale.",
            ],
            "es": [
                "Proteína vegetal y fibra en un solo alimento.",
                "Ayudan a controlar el apetito y el azúcar.",
                "Fuente de folato y hierro.",
                "Apoyan la salud intestinal.",
            ],
            "fr": [
                "Protéines végétales et fibres en un seul aliment.",
                "Aident à contrôler l'appétit et la glycémie.",
                "Source de folates et de fer.",
                "Soutiennent la santé intestinale.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "chickpea curry"},
            "salad": {"source_id": "eatingwell", "query": "chickpea salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "chickpea breakfast"},
        },
    },
    {
        "id": "almonds",
        "emoji": "\U0001F95C",
        "name": {"ru": "Миндаль", "en": "Almonds", "it": "Mandorle", "es": "Almendras", "fr": "Amandes"},
        "benefits": {
            "ru": [
                "Витамин E защищает клетки как антиоксидант.",
                "Полезные жиры поддерживают сердце.",
                "Белок и клетчатка дают сытость.",
                "Источник магния и кальция.",
            ],
            "en": [
                "Vitamin E protects cells as an antioxidant.",
                "Healthy fats support the heart.",
                "Protein and fiber keep you full.",
                "A source of magnesium and calcium.",
            ],
            "it": [
                "La vitamina E protegge le cellule come antiossidante.",
                "I grassi sani sostengono il cuore.",
                "Proteine e fibra saziano.",
                "Fonte di magnesio e calcio.",
            ],
            "es": [
                "La vitamina E protege las células como antioxidante.",
                "Las grasas sanas apoyan el corazón.",
                "Proteína y fibra que sacian.",
                "Fuente de magnesio y calcio.",
            ],
            "fr": [
                "La vitamine E protège les cellules comme antioxydant.",
                "Les bons gras soutiennent le cœur.",
                "Protéines et fibres rassasiantes.",
                "Source de magnésium et de calcium.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "almond crusted dinner"},
            "salad": {"source_id": "eatingwell", "query": "almond salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "almond breakfast"},
        },
    },
    {
        "id": "beetroot",
        "emoji": "\U0001FADB",
        "name": {"ru": "Свёкла", "en": "Beetroot", "it": "Barbabietola", "es": "Remolacha", "fr": "Betterave"},
        "benefits": {
            "ru": [
                "Нитраты помогают снижать давление.",
                "Поддерживает выносливость и кровоток.",
                "Богата фолиевой кислотой и марганцем.",
                "Антиоксиданты-беталаины борются с воспалением.",
            ],
            "en": [
                "Nitrates help lower blood pressure.",
                "Supports stamina and blood flow.",
                "Rich in folate and manganese.",
                "Betalain antioxidants fight inflammation.",
            ],
            "it": [
                "I nitrati aiutano ad abbassare la pressione.",
                "Sostiene resistenza e circolazione.",
                "Ricca di folati e manganese.",
                "Gli antiossidanti betalaine combattono l'infiammazione.",
            ],
            "es": [
                "Los nitratos ayudan a bajar la presión arterial.",
                "Apoya la resistencia y el flujo sanguíneo.",
                "Rica en folato y manganeso.",
                "Las betalaínas combaten la inflamación.",
            ],
            "fr": [
                "Les nitrates aident à réduire la tension.",
                "Soutient l'endurance et la circulation.",
                "Riche en folates et en manganèse.",
                "Les bétalaïnes combattent l'inflammation.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "beetroot dinner"},
            "salad": {"source_id": "eatingwell", "query": "beet salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "beetroot breakfast"},
        },
    },
    {
        "id": "banana",
        "emoji": "\U0001F34C",
        "name": {"ru": "Банан", "en": "Banana", "it": "Banana", "es": "Plátano", "fr": "Banane"},
        "benefits": {
            "ru": [
                "Калий поддерживает сердце и мышцы.",
                "Быстрая натуральная энергия.",
                "Витамин B6 для работы нервной системы.",
                "Пребиотики питают полезные бактерии.",
            ],
            "en": [
                "Potassium supports the heart and muscles.",
                "Quick natural energy.",
                "Vitamin B6 for the nervous system.",
                "Prebiotics feed good gut bacteria.",
            ],
            "it": [
                "Il potassio sostiene cuore e muscoli.",
                "Energia naturale e rapida.",
                "Vitamina B6 per il sistema nervoso.",
                "I prebiotici nutrono i batteri buoni.",
            ],
            "es": [
                "El potasio apoya el corazón y los músculos.",
                "Energía natural y rápida.",
                "Vitamina B6 para el sistema nervioso.",
                "Los prebióticos alimentan la flora buena.",
            ],
            "fr": [
                "Le potassium soutient le cœur et les muscles.",
                "Une énergie naturelle et rapide.",
                "Vitamine B6 pour le système nerveux.",
                "Les prébiotiques nourrissent les bonnes bactéries.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "banana curry"},
            "salad": {"source_id": "eatingwell", "query": "banana fruit salad"},
            "breakfast": {"source_id": "harvard", "query": "banana"},
        },
    },
    {
        "id": "garlic",
        "emoji": "\U0001F9C4",
        "name": {"ru": "Чеснок", "en": "Garlic", "it": "Aglio", "es": "Ajo", "fr": "Ail"},
        "benefits": {
            "ru": [
                "Аллицин поддерживает иммунитет.",
                "Помогает здоровью сердца и сосудов.",
                "Обладает антибактериальными свойствами.",
                "Добавляет вкус без лишней соли.",
            ],
            "en": [
                "Allicin supports immunity.",
                "Helps heart and vascular health.",
                "Has antibacterial properties.",
                "Adds flavor without extra salt.",
            ],
            "it": [
                "L'allicina sostiene l'immunità.",
                "Aiuta la salute di cuore e vasi.",
                "Ha proprietà antibatteriche.",
                "Dà sapore senza sale aggiunto.",
            ],
            "es": [
                "La alicina apoya la inmunidad.",
                "Ayuda a la salud del corazón y los vasos.",
                "Tiene propiedades antibacterianas.",
                "Aporta sabor sin sal extra.",
            ],
            "fr": [
                "L'allicine soutient l'immunité.",
                "Aide la santé du cœur et des vaisseaux.",
                "Possède des propriétés antibactériennes.",
                "Apporte du goût sans sel ajouté.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "garlic chicken"},
            "salad": {"source_id": "eatingwell", "query": "garlic dressing salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "garlic mushroom breakfast"},
        },
    },
    {
        "id": "carrot",
        "emoji": "\U0001F955",
        "name": {"ru": "Морковь", "en": "Carrot", "it": "Carota", "es": "Zanahoria", "fr": "Carotte"},
        "benefits": {
            "ru": [
                "Бета-каротин превращается в витамин A для зрения.",
                "Клетчатка поддерживает пищеварение.",
                "Антиоксиданты полезны для кожи.",
                "Низкая калорийность, хрустящий перекус.",
            ],
            "en": [
                "Beta-carotene converts to vitamin A for eyesight.",
                "Fiber supports digestion.",
                "Antioxidants benefit the skin.",
                "Low-calorie, crunchy snack.",
            ],
            "it": [
                "Il beta-carotene diventa vitamina A per la vista.",
                "La fibra sostiene la digestione.",
                "Gli antiossidanti fanno bene alla pelle.",
                "Spuntino croccante e ipocalorico.",
            ],
            "es": [
                "El betacaroteno se convierte en vitamina A para la vista.",
                "La fibra apoya la digestión.",
                "Los antioxidantes benefician la piel.",
                "Snack crujiente y bajo en calorías.",
            ],
            "fr": [
                "Le bêta-carotène devient vitamine A pour la vue.",
                "Les fibres soutiennent la digestion.",
                "Les antioxydants sont bons pour la peau.",
                "En-cas croquant et peu calorique.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "carrot soup"},
            "salad": {"source_id": "eatingwell", "query": "carrot salad"},
            "breakfast": {"source_id": "eatingwell", "query": "carrot oatmeal breakfast"},
        },
    },
    {
        "id": "olive_oil",
        "emoji": "\U0001FAD2",
        "name": {"ru": "Оливковое масло", "en": "Olive Oil", "it": "Olio d'oliva", "es": "Aceite de oliva", "fr": "Huile d'olive"},
        "benefits": {
            "ru": [
                "Основа средиземноморской диеты для сердца.",
                "Полифенолы обладают противовоспалительным действием.",
                "Полезные мононенасыщенные жиры.",
                "Помогает усваивать витамины из овощей.",
            ],
            "en": [
                "A heart-healthy Mediterranean-diet staple.",
                "Polyphenols are anti-inflammatory.",
                "Beneficial monounsaturated fats.",
                "Helps absorb vitamins from vegetables.",
            ],
            "it": [
                "Pilastro della dieta mediterranea, amico del cuore.",
                "I polifenoli sono antinfiammatori.",
                "Grassi monoinsaturi benefici.",
                "Aiuta ad assorbire le vitamine dalle verdure.",
            ],
            "es": [
                "Pilar de la dieta mediterránea, bueno para el corazón.",
                "Los polifenoles son antiinflamatorios.",
                "Grasas monoinsaturadas beneficiosas.",
                "Ayuda a absorber vitaminas de las verduras.",
            ],
            "fr": [
                "Pilier du régime méditerranéen, bon pour le cœur.",
                "Les polyphénols sont anti-inflammatoires.",
                "De bons gras mono-insaturés.",
                "Aide à absorber les vitamines des légumes.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "olive oil mediterranean dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "olive oil salad dressing"},
            "breakfast": {"source_id": "eatingwell", "query": "mediterranean breakfast"},
        },
    },
    {
        "id": "berries_strawberry",
        "emoji": "\U0001F353",
        "name": {"ru": "Клубника", "en": "Strawberry", "it": "Fragola", "es": "Fresa", "fr": "Fraise"},
        "benefits": {
            "ru": [
                "Очень богата витамином C.",
                "Антиоксиданты поддерживают сердце.",
                "Мало сахара, много клетчатки.",
                "Помогает здоровью кожи.",
            ],
            "en": [
                "Very high in vitamin C.",
                "Antioxidants support the heart.",
                "Low in sugar, high in fiber.",
                "Helps skin health.",
            ],
            "it": [
                "Ricchissima di vitamina C.",
                "Gli antiossidanti sostengono il cuore.",
                "Pochi zuccheri, tanta fibra.",
                "Aiuta la salute della pelle.",
            ],
            "es": [
                "Muy rica en vitamina C.",
                "Los antioxidantes apoyan el corazón.",
                "Baja en azúcar, alta en fibra.",
                "Ayuda a la salud de la piel.",
            ],
            "fr": [
                "Très riche en vitamine C.",
                "Les antioxydants soutiennent le cœur.",
                "Peu de sucre, beaucoup de fibres.",
                "Bonne pour la santé de la peau.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "strawberry chicken"},
            "salad": {"source_id": "bbcgoodfood", "query": "strawberry salad"},
            "breakfast": {"source_id": "eatingwell", "query": "strawberry breakfast"},
        },
    },
    {
        "id": "pumpkin",
        "emoji": "\U0001F383",
        "name": {"ru": "Тыква", "en": "Pumpkin", "it": "Zucca", "es": "Calabaza", "fr": "Citrouille"},
        "benefits": {
            "ru": [
                "Бета-каротин для зрения и иммунитета.",
                "Богата клетчаткой при низкой калорийности.",
                "Калий поддерживает давление.",
                "Антиоксиданты защищают клетки.",
            ],
            "en": [
                "Beta-carotene for eyesight and immunity.",
                "High in fiber, low in calories.",
                "Potassium supports blood pressure.",
                "Antioxidants protect cells.",
            ],
            "it": [
                "Beta-carotene per vista e immunità.",
                "Ricca di fibra e povera di calorie.",
                "Il potassio sostiene la pressione.",
                "Gli antiossidanti proteggono le cellule.",
            ],
            "es": [
                "Betacaroteno para la vista y la inmunidad.",
                "Alta en fibra y baja en calorías.",
                "El potasio apoya la presión arterial.",
                "Los antioxidantes protegen las células.",
            ],
            "fr": [
                "Bêta-carotène pour la vue et l'immunité.",
                "Riche en fibres, peu calorique.",
                "Le potassium soutient la tension.",
                "Les antioxydants protègent les cellules.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "pumpkin soup"},
            "salad": {"source_id": "eatingwell", "query": "roasted pumpkin salad"},
            "breakfast": {"source_id": "eatingwell", "query": "pumpkin oatmeal breakfast"},
        },
    },
    {
        "id": "green_tea",
        "emoji": "\U0001F375",
        "name": {"ru": "Зелёный чай", "en": "Green Tea", "it": "Tè verde", "es": "Té verde", "fr": "Thé vert"},
        "benefits": {
            "ru": [
                "Катехины — мощные антиоксиданты.",
                "Мягкая энергия без скачков сахара.",
                "Поддерживает обмен веществ.",
                "Полезен для сердца и сосудов.",
            ],
            "en": [
                "Catechins are powerful antioxidants.",
                "Gentle energy without sugar spikes.",
                "Supports metabolism.",
                "Good for heart and vessels.",
            ],
            "it": [
                "Le catechine sono potenti antiossidanti.",
                "Energia delicata senza picchi glicemici.",
                "Sostiene il metabolismo.",
                "Fa bene a cuore e vasi.",
            ],
            "es": [
                "Las catequinas son potentes antioxidantes.",
                "Energía suave sin picos de azúcar.",
                "Apoya el metabolismo.",
                "Bueno para el corazón y los vasos.",
            ],
            "fr": [
                "Les catéchines sont de puissants antioxydants.",
                "Une énergie douce sans pic de sucre.",
                "Soutient le métabolisme.",
                "Bon pour le cœur et les vaisseaux.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "matcha green tea recipe"},
            "salad": {"source_id": "eatingwell", "query": "green tea dressing"},
            "breakfast": {"source_id": "eatingwell", "query": "matcha breakfast"},
        },
    },
    {
        "id": "bell_pepper",
        "emoji": "\U0001FAD1",
        "name": {"ru": "Болгарский перец", "en": "Bell Pepper", "it": "Peperone", "es": "Pimiento", "fr": "Poivron"},
        "benefits": {
            "ru": [
                "Больше витамина C, чем в апельсине.",
                "Антиоксиданты для кожи и иммунитета.",
                "Мало калорий, много вкуса.",
                "Источник витамина A и B6.",
            ],
            "en": [
                "More vitamin C than an orange.",
                "Antioxidants for skin and immunity.",
                "Low in calories, big on flavor.",
                "A source of vitamin A and B6.",
            ],
            "it": [
                "Più vitamina C di un'arancia.",
                "Antiossidanti per pelle e immunità.",
                "Poche calorie, tanto sapore.",
                "Fonte di vitamina A e B6.",
            ],
            "es": [
                "Más vitamina C que una naranja.",
                "Antioxidantes para la piel y la inmunidad.",
                "Pocas calorías, mucho sabor.",
                "Fuente de vitamina A y B6.",
            ],
            "fr": [
                "Plus de vitamine C qu'une orange.",
                "Antioxydants pour la peau et l'immunité.",
                "Peu de calories, beaucoup de goût.",
                "Source de vitamine A et B6.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "stuffed bell pepper"},
            "salad": {"source_id": "eatingwell", "query": "bell pepper salad"},
            "breakfast": {"source_id": "eatingwell", "query": "bell pepper egg breakfast"},
        },
    },
    {
        "id": "chia",
        "emoji": "\U0001F331",
        "name": {"ru": "Семена чиа", "en": "Chia Seeds", "it": "Semi di chia", "es": "Semillas de chía", "fr": "Graines de chia"},
        "benefits": {
            "ru": [
                "Растительные омега-3 (ALA) для сердца.",
                "Очень много клетчатки.",
                "Впитывают воду и дают сытость.",
                "Источник кальция и магния.",
            ],
            "en": [
                "Plant omega-3 (ALA) for the heart.",
                "Exceptionally high in fiber.",
                "Absorb water and promote fullness.",
                "A source of calcium and magnesium.",
            ],
            "it": [
                "Omega-3 vegetali (ALA) per il cuore.",
                "Eccezionalmente ricchi di fibra.",
                "Assorbono acqua e saziano.",
                "Fonte di calcio e magnesio.",
            ],
            "es": [
                "Omega-3 vegetal (ALA) para el corazón.",
                "Excepcionalmente ricas en fibra.",
                "Absorben agua y dan saciedad.",
                "Fuente de calcio y magnesio.",
            ],
            "fr": [
                "Oméga-3 végétal (ALA) pour le cœur.",
                "Exceptionnellement riches en fibres.",
                "Absorbent l'eau et rassasient.",
                "Source de calcium et de magnésium.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "chia crusted dinner"},
            "salad": {"source_id": "eatingwell", "query": "chia salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "chia pudding breakfast"},
        },
    },
    {
        "id": "mushroom",
        "emoji": "\U0001F344",
        "name": {"ru": "Грибы", "en": "Mushrooms", "it": "Funghi", "es": "Setas", "fr": "Champignons"},
        "benefits": {
            "ru": [
                "Низкая калорийность и умами-вкус.",
                "Источник витаминов группы B.",
                "Поддерживают иммунитет бета-глюканами.",
                "Единственный растительный источник витамина D (на солнце).",
            ],
            "en": [
                "Low in calories with savory umami.",
                "A source of B vitamins.",
                "Beta-glucans support immunity.",
                "The only plant source of vitamin D (sun-exposed).",
            ],
            "it": [
                "Pochi calorie e gusto umami.",
                "Fonte di vitamine del gruppo B.",
                "I beta-glucani sostengono l'immunità.",
                "Unica fonte vegetale di vitamina D (al sole).",
            ],
            "es": [
                "Pocas calorías y sabor umami.",
                "Fuente de vitaminas del grupo B.",
                "Los betaglucanos apoyan la inmunidad.",
                "Única fuente vegetal de vitamina D (al sol).",
            ],
            "fr": [
                "Peu de calories et un goût umami.",
                "Source de vitamines B.",
                "Les bêta-glucanes soutiennent l'immunité.",
                "Seule source végétale de vitamine D (au soleil).",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "mushroom risotto"},
            "salad": {"source_id": "eatingwell", "query": "mushroom salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "mushroom breakfast"},
        },
    },
    {
        "id": "orange",
        "emoji": "\U0001F34A",
        "name": {"ru": "Апельсин", "en": "Orange", "it": "Arancia", "es": "Naranja", "fr": "Orange"},
        "benefits": {
            "ru": [
                "Классический источник витамина C.",
                "Клетчатка и натуральная сладость.",
                "Флавоноиды поддерживают сердце.",
                "Помогает усваивать железо из растений.",
            ],
            "en": [
                "A classic source of vitamin C.",
                "Fiber with natural sweetness.",
                "Flavonoids support the heart.",
                "Helps absorb plant iron.",
            ],
            "it": [
                "Fonte classica di vitamina C.",
                "Fibra e dolcezza naturale.",
                "I flavonoidi sostengono il cuore.",
                "Aiuta ad assorbire il ferro vegetale.",
            ],
            "es": [
                "Fuente clásica de vitamina C.",
                "Fibra con dulzor natural.",
                "Los flavonoides apoyan el corazón.",
                "Ayuda a absorber el hierro vegetal.",
            ],
            "fr": [
                "Source classique de vitamine C.",
                "Des fibres et une douceur naturelle.",
                "Les flavonoïdes soutiennent le cœur.",
                "Aide à absorber le fer végétal.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "orange glazed chicken"},
            "salad": {"source_id": "eatingwell", "query": "orange salad"},
            "breakfast": {"source_id": "eatingwell", "query": "orange citrus breakfast"},
        },
    },
    {
        "id": "cauliflower",
        "emoji": "\U0001F966",
        "name": {"ru": "Цветная капуста", "en": "Cauliflower", "it": "Cavolfiore", "es": "Coliflor", "fr": "Chou-fleur"},
        "benefits": {
            "ru": [
                "Низкоуглеводная замена крупам и картофелю.",
                "Богата витамином C и витамином K.",
                "Содержит сульфорафан против воспаления.",
                "Клетчатка для пищеварения.",
            ],
            "en": [
                "A low-carb swap for grains and potatoes.",
                "Rich in vitamin C and vitamin K.",
                "Contains anti-inflammatory sulforaphane.",
                "Fiber for digestion.",
            ],
            "it": [
                "Alternativa a basso contenuto di carboidrati.",
                "Ricco di vitamina C e vitamina K.",
                "Contiene sulforafano antinfiammatorio.",
                "Fibra per la digestione.",
            ],
            "es": [
                "Alternativa baja en carbohidratos.",
                "Rica en vitamina C y vitamina K.",
                "Contiene sulforafano antiinflamatorio.",
                "Fibra para la digestión.",
            ],
            "fr": [
                "Une alternative pauvre en glucides.",
                "Riche en vitamine C et vitamine K.",
                "Contient du sulforaphane anti-inflammatoire.",
                "Des fibres pour la digestion.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "cauliflower dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "cauliflower salad"},
            "breakfast": {"source_id": "eatingwell", "query": "cauliflower breakfast"},
        },
    },
    {
        "id": "ginger",
        "emoji": "\U0001FADA",
        "name": {"ru": "Имбирь", "en": "Ginger", "it": "Zenzero", "es": "Jengibre", "fr": "Gingembre"},
        "benefits": {
            "ru": [
                "Помогает при тошноте и пищеварении.",
                "Гингерол обладает противовоспалительным действием.",
                "Поддерживает иммунитет.",
                "Добавляет вкус без соли и сахара.",
            ],
            "en": [
                "Helps with nausea and digestion.",
                "Gingerol is anti-inflammatory.",
                "Supports immunity.",
                "Adds flavor without salt or sugar.",
            ],
            "it": [
                "Aiuta con nausea e digestione.",
                "Il gingerolo è antinfiammatorio.",
                "Sostiene l'immunità.",
                "Dà sapore senza sale né zucchero.",
            ],
            "es": [
                "Ayuda con las náuseas y la digestión.",
                "El gingerol es antiinflamatorio.",
                "Apoya la inmunidad.",
                "Aporta sabor sin sal ni azúcar.",
            ],
            "fr": [
                "Aide en cas de nausée et pour la digestion.",
                "Le gingérol est anti-inflammatoire.",
                "Soutient l'immunité.",
                "Apporte du goût sans sel ni sucre.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "ginger stir fry"},
            "salad": {"source_id": "eatingwell", "query": "ginger dressing salad"},
            "breakfast": {"source_id": "eatingwell", "query": "ginger smoothie breakfast"},
        },
    },
    {
        "id": "tuna",
        "emoji": "\U0001F41F",
        "name": {"ru": "Тунец", "en": "Tuna", "it": "Tonno", "es": "Atún", "fr": "Thon"},
        "benefits": {
            "ru": [
                "Постный высококачественный белок.",
                "Омега-3 для сердца и мозга.",
                "Источник селена и витамина B12.",
                "Удобно и быстро готовить.",
            ],
            "en": [
                "Lean, high-quality protein.",
                "Omega-3 for heart and brain.",
                "A source of selenium and vitamin B12.",
                "Quick and convenient to prepare.",
            ],
            "it": [
                "Proteine magre di alta qualità.",
                "Omega-3 per cuore e cervello.",
                "Fonte di selenio e vitamina B12.",
                "Veloce e pratico da preparare.",
            ],
            "es": [
                "Proteína magra de alta calidad.",
                "Omega-3 para el corazón y el cerebro.",
                "Fuente de selenio y vitamina B12.",
                "Rápido y práctico de preparar.",
            ],
            "fr": [
                "Protéine maigre de haute qualité.",
                "Oméga-3 pour le cœur et le cerveau.",
                "Source de sélénium et de vitamine B12.",
                "Rapide et pratique à préparer.",
            ],
        },
        "recipes": {
            "main": {"source_id": "heart", "query": "tuna"},
            "salad": {"source_id": "eatingwell", "query": "tuna salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "tuna breakfast"},
        },
    },
    {
        "id": "cucumber",
        "emoji": "\U0001F952",
        "name": {"ru": "Огурец", "en": "Cucumber", "it": "Cetriolo", "es": "Pepino", "fr": "Concombre"},
        "benefits": {
            "ru": [
                "Очень увлажняет — почти на 95% состоит из воды.",
                "Мало калорий, освежающий вкус.",
                "Содержит витамин K и калий.",
                "Антиоксиданты полезны для кожи.",
            ],
            "en": [
                "Very hydrating — about 95% water.",
                "Low in calories and refreshing.",
                "Contains vitamin K and potassium.",
                "Antioxidants benefit the skin.",
            ],
            "it": [
                "Molto idratante: circa il 95% di acqua.",
                "Poche calorie e rinfrescante.",
                "Contiene vitamina K e potassio.",
                "Gli antiossidanti fanno bene alla pelle.",
            ],
            "es": [
                "Muy hidratante: cerca del 95% agua.",
                "Bajo en calorías y refrescante.",
                "Contiene vitamina K y potasio.",
                "Los antioxidantes benefician la piel.",
            ],
            "fr": [
                "Très hydratant : environ 95 % d'eau.",
                "Peu calorique et rafraîchissant.",
                "Contient de la vitamine K et du potassium.",
                "Les antioxydants sont bons pour la peau.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "cucumber noodle dinner"},
            "salad": {"source_id": "eatingwell", "query": "cucumber salad"},
            "breakfast": {"source_id": "eatingwell", "query": "cucumber breakfast"},
        },
    },
    {
        "id": "apple",
        "emoji": "\U0001F34E",
        "name": {"ru": "Яблоко", "en": "Apple", "it": "Mela", "es": "Manzana", "fr": "Pomme"},
        "benefits": {
            "ru": [
                "Пектин — растворимая клетчатка для кишечника.",
                "Помогает контролировать холестерин.",
                "Антиоксиданты для сердца.",
                "Натуральная сладость и сытость.",
            ],
            "en": [
                "Pectin is soluble fiber for the gut.",
                "Helps manage cholesterol.",
                "Antioxidants for the heart.",
                "Natural sweetness and fullness.",
            ],
            "it": [
                "La pectina è fibra solubile per l'intestino.",
                "Aiuta a gestire il colesterolo.",
                "Antiossidanti per il cuore.",
                "Dolcezza naturale e sazietà.",
            ],
            "es": [
                "La pectina es fibra soluble para el intestino.",
                "Ayuda a controlar el colesterol.",
                "Antioxidantes para el corazón.",
                "Dulzor natural y saciedad.",
            ],
            "fr": [
                "La pectine est une fibre soluble pour l'intestin.",
                "Aide à gérer le cholestérol.",
                "Antioxydants pour le cœur.",
                "Douceur naturelle et satiété.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "apple pork dinner"},
            "salad": {"source_id": "eatingwell", "query": "apple salad"},
            "breakfast": {"source_id": "harvard", "query": "apple"},
        },
    },
    {
        "id": "edamame",
        "emoji": "\U0001FAD8",
        "name": {"ru": "Эдамаме", "en": "Edamame", "it": "Edamame", "es": "Edamame", "fr": "Edamame"},
        "benefits": {
            "ru": [
                "Полноценный растительный белок.",
                "Клетчатка и фолиевая кислота.",
                "Изофлавоны полезны для сердца.",
                "Удобный белковый перекус.",
            ],
            "en": [
                "Complete plant protein.",
                "Fiber and folate.",
                "Isoflavones support the heart.",
                "A convenient protein snack.",
            ],
            "it": [
                "Proteina vegetale completa.",
                "Fibra e folati.",
                "Gli isoflavoni sostengono il cuore.",
                "Spuntino proteico pratico.",
            ],
            "es": [
                "Proteína vegetal completa.",
                "Fibra y folato.",
                "Las isoflavonas apoyan el corazón.",
                "Un snack proteico práctico.",
            ],
            "fr": [
                "Protéine végétale complète.",
                "Fibres et folates.",
                "Les isoflavones soutiennent le cœur.",
                "Un en-cas protéiné pratique.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "edamame stir fry"},
            "salad": {"source_id": "eatingwell", "query": "edamame salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "edamame breakfast bowl"},
        },
    },
    {
        "id": "cabbage",
        "emoji": "\U0001F96C",
        "name": {"ru": "Капуста", "en": "Cabbage", "it": "Cavolo", "es": "Repollo", "fr": "Chou"},
        "benefits": {
            "ru": [
                "Очень мало калорий, много клетчатки.",
                "Витамин C и витамин K.",
                "Квашеная капуста — источник пробиотиков.",
                "Поддерживает пищеварение.",
            ],
            "en": [
                "Very low in calories, high in fiber.",
                "Vitamin C and vitamin K.",
                "Fermented cabbage is a probiotic source.",
                "Supports digestion.",
            ],
            "it": [
                "Pochissime calorie, tanta fibra.",
                "Vitamina C e vitamina K.",
                "I crauti sono fonte di probiotici.",
                "Sostiene la digestione.",
            ],
            "es": [
                "Muy bajo en calorías, alto en fibra.",
                "Vitamina C y vitamina K.",
                "El chucrut es fuente de probióticos.",
                "Apoya la digestión.",
            ],
            "fr": [
                "Très peu de calories, riche en fibres.",
                "Vitamine C et vitamine K.",
                "La choucroute est source de probiotiques.",
                "Soutient la digestion.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "cabbage stir fry"},
            "salad": {"source_id": "eatingwell", "query": "cabbage slaw salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "cabbage breakfast hash"},
        },
    },
    {
        "id": "zucchini",
        "emoji": "🥒",
        "name": {"ru": "Кабачок", "en": "Zucchini", "it": "Zucchine", "es": "Calabacín", "fr": "Courgette"},
        "benefits": {
            "ru": [
                "Очень мало калорий и много воды — отлично подходит для контроля веса и гидратации.",
                "Содержит витамин C и калий, поддерживающие иммунитет и нормальное давление.",
                "Богат антиоксидантами лютеином и зеаксантином, защищающими зрение.",
                "Растворимая клетчатка улучшает пищеварение и питает полезную микрофлору кишечника.",
            ],
            "en": [
                "Very low in calories and high in water, supporting hydration and weight management.",
                "Provides vitamin C and potassium for immune support and healthy blood pressure.",
                "Rich in antioxidants like lutein and zeaxanthin that protect eye health.",
                "Contains soluble fiber that aids digestion and feeds beneficial gut bacteria.",
            ],
            "it": [
                "Pochissime calorie e alto contenuto d'acqua: ideale per l'idratazione e il controllo del peso.",
                "Fornisce vitamina C e potassio a supporto del sistema immunitario e della pressione arteriosa.",
                "Ricco di antiossidanti come luteina e zeaxantina che proteggono la vista.",
                "La fibra solubile favorisce la digestione e nutre i batteri intestinali benefici.",
            ],
            "es": [
                "Muy bajo en calorías y rico en agua, ideal para la hidratación y el control de peso.",
                "Aporta vitamina C y potasio para fortalecer el sistema inmune y mantener una presión arterial saludable.",
                "Rico en antioxidantes como la luteína y la zeaxantina, que protegen la salud ocular.",
                "Su fibra soluble mejora la digestión y alimenta la microbiota intestinal beneficiosa.",
            ],
            "fr": [
                "Très peu calorique et riche en eau, il favorise l'hydratation et la gestion du poids.",
                "Apporte de la vitamine C et du potassium pour soutenir l'immunité et une pression artérielle saine.",
                "Riche en antioxydants comme la lutéine et la zéaxanthine, qui protègent la santé oculaire.",
                "Sa fibre soluble améliore la digestion et nourrit les bonnes bactéries intestinales.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "zucchini dinner"},
            "salad": {"source_id": "eatingwell", "query": "zucchini salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "zucchini fritters breakfast"},
        },
    },
    {
        "id": "eggplant",
        "emoji": "🍆",
        "name": {"ru": "Баклажан", "en": "Eggplant", "it": "Melanzana", "es": "Berenjena", "fr": "Aubergine"},
        "benefits": {
            "ru": [
                "Содержит насунин — мощный антиоксидант в кожуре, защищающий клетки мозга.",
                "Хороший источник клетчатки, которая поддерживает пищеварение и стабилизирует сахар в крови.",
                "Богат хлорогеновой кислотой, снижающей уровень «плохого» холестерина и воспаление.",
                "Мало калорий и много воды — идеально для контроля веса.",
            ],
            "en": [
                "Contains nasunin, a powerful antioxidant in the skin that protects brain cell membranes.",
                "Good source of fiber supporting healthy digestion and blood sugar control.",
                "Rich in chlorogenic acid, shown to lower LDL cholesterol and have anti-inflammatory effects.",
                "Low in calories and high in water content, making it excellent for weight management.",
            ],
            "it": [
                "Contiene nasunina, un potente antiossidante nella buccia che protegge le membrane delle cellule cerebrali.",
                "Buona fonte di fibre che favoriscono la digestione e il controllo della glicemia.",
                "Ricco di acido clorogenico, che abbassa il colesterolo LDL e ha effetti antinfiammatori.",
                "Povero di calorie e ricco d'acqua, ideale per la gestione del peso.",
            ],
            "es": [
                "Contiene nasunina, un potente antioxidante de la piel que protege las membranas de las células cerebrales.",
                "Buena fuente de fibra que favorece la digestión saludable y el control del azúcar en sangre.",
                "Rico en ácido clorogénico, que reduce el colesterol LDL y tiene efectos antiinflamatorios.",
                "Bajo en calorías y alto en agua, perfecto para el control del peso.",
            ],
            "fr": [
                "Contient de la nasunine, un puissant antioxydant de la peau qui protège les membranes des cellules cérébrales.",
                "Bonne source de fibres favorisant une digestion saine et le contrôle de la glycémie.",
                "Riche en acide chlorogénique, qui abaisse le cholestérol LDL et a des effets anti-inflammatoires.",
                "Peu calorique et riche en eau, excellent pour la gestion du poids.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "eggplant dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "eggplant salad"},
            "breakfast": {"source_id": "eatingwell", "query": "eggplant breakfast recipes"},
        },
    },
    {
        "id": "asparagus",
        "emoji": "🌿",
        "name": {"ru": "Спаржа", "en": "Asparagus", "it": "Asparago", "es": "Espárrago", "fr": "Asperge"},
        "benefits": {
            "ru": [
                "Отличный источник фолиевой кислоты, необходимой для синтеза ДНК и здорового деления клеток.",
                "Содержит инулин — пребиотик, питающий полезные бактерии кишечника.",
                "Богата витамином K, необходимым для здоровья костей и свёртываемости крови.",
                "Содержит антиоксиданты: витамин E, а также флавоноиды кверцетин и рутин.",
            ],
            "en": [
                "Excellent source of folate, essential for DNA synthesis and healthy cell division.",
                "Contains inulin, a prebiotic fiber that nourishes beneficial gut bacteria.",
                "Rich in vitamin K supporting bone health and proper blood clotting.",
                "Provides antioxidants including vitamin E and the flavonoids quercetin and rutin.",
            ],
            "it": [
                "Ottima fonte di folati, essenziali per la sintesi del DNA e la corretta divisione cellulare.",
                "Contiene inulina, una fibra prebiotica che nutre i batteri intestinali benefici.",
                "Ricca di vitamina K, a supporto della salute ossea e della coagulazione del sangue.",
                "Apporta antiossidanti come la vitamina E e i flavonoidi quercetina e rutina.",
            ],
            "es": [
                "Excelente fuente de folato, esencial para la síntesis de ADN y la división celular saludable.",
                "Contiene inulina, una fibra prebiótica que nutre las bacterias intestinales beneficiosas.",
                "Rica en vitamina K, que favorece la salud ósea y la correcta coagulación de la sangre.",
                "Aporta antioxidantes como la vitamina E y los flavonoides quercetina y rutina.",
            ],
            "fr": [
                "Excellente source de folate, essentiel à la synthèse de l'ADN et à la division cellulaire saine.",
                "Contient de l'inuline, une fibre prébiotique qui nourrit les bonnes bactéries intestinales.",
                "Riche en vitamine K, soutenant la santé osseuse et une bonne coagulation sanguine.",
                "Apporte des antioxydants comme la vitamine E et les flavonoïdes quercétine et rutine.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "asparagus dinner"},
            "salad": {"source_id": "eatingwell", "query": "asparagus salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "asparagus eggs breakfast"},
        },
    },
    {
        "id": "celery",
        "emoji": "🥬",
        "name": {"ru": "Сельдерей", "en": "Celery", "it": "Sedano", "es": "Apio", "fr": "Céleri"},
        "benefits": {
            "ru": [
                "Минимум калорий и высокое содержание воды — один из лучших перекусов для гидратации.",
                "Содержит фталиды, которые помогают расслабить стенки артерий и снизить артериальное давление.",
                "Богат витамином K, фолиевой кислотой и калием, важными для сердца и костей.",
                "Содержит антиоксидантный флавоноид апигенин с противовоспалительными свойствами.",
            ],
            "en": [
                "Exceptionally low in calories with high water content, making it a top hydrating snack.",
                "Contains phthalides that may help relax artery walls and lower blood pressure.",
                "Provides vitamin K, folate, and potassium important for heart and bone health.",
                "Rich in antioxidant flavonoids including apigenin, which has anti-inflammatory properties.",
            ],
            "it": [
                "Pochissime calorie e alto contenuto d'acqua: uno degli spuntini più idratanti in assoluto.",
                "Contiene ftalidi che possono aiutare a rilassare le pareti delle arterie e abbassare la pressione.",
                "Fornisce vitamina K, folati e potassio, importanti per la salute di cuore e ossa.",
                "Ricco di flavonoidi antiossidanti come l'apigenina, dalle proprietà antinfiammatorie.",
            ],
            "es": [
                "Bajísimo en calorías y con alto contenido de agua, uno de los mejores snacks hidratantes.",
                "Contiene ftalidas que pueden ayudar a relajar las paredes arteriales y reducir la presión arterial.",
                "Aporta vitamina K, folato y potasio, importantes para la salud del corazón y los huesos.",
                "Rico en flavonoides antioxidantes como la apigenina, con propiedades antiinflamatorias.",
            ],
            "fr": [
                "Très peu calorique et très hydratant grâce à sa haute teneur en eau.",
                "Contient des phtalides qui peuvent aider à détendre les parois artérielles et abaisser la pression.",
                "Apporte de la vitamine K, des folates et du potassium, bénéfiques pour le cœur et les os.",
                "Riche en flavonoïdes antioxydants comme l'apigénine, aux propriétés anti-inflammatoires.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "celery soup recipes"},
            "salad": {"source_id": "eatingwell", "query": "celery salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "celery juice breakfast"},
        },
    },
    {
        "id": "brussels_sprouts",
        "emoji": "🥬",
        "name": {"ru": "Брюссельская капуста", "en": "Brussels sprouts", "it": "Cavoletti di Bruxelles", "es": "Coles de Bruselas", "fr": "Choux de Bruxelles"},
        "benefits": {
            "ru": [
                "Исключительно богаты витамином C — одна чашка даёт более 100% суточной нормы.",
                "Содержат глюкозинолаты — соединения, связанные со снижением риска онкологических заболеваний.",
                "Высокое содержание витамина K, необходимого для прочности костей и свёртываемости крови.",
                "Хороший источник фолиевой кислоты и клетчатки, полезных для сердца и пищеварения.",
            ],
            "en": [
                "Exceptionally rich in vitamin C — one cup provides over 100% of the daily requirement.",
                "Contains glucosinolates, compounds linked to reduced cancer risk in population studies.",
                "High in vitamin K essential for bone strength and blood coagulation.",
                "Good source of folate and fiber supporting heart health and healthy digestion.",
            ],
            "it": [
                "Eccezionalmente ricchi di vitamina C: una tazza copre oltre il 100% del fabbisogno giornaliero.",
                "Contengono glucosinolati, composti associati a una riduzione del rischio di cancro.",
                "Alto contenuto di vitamina K, essenziale per la solidità ossea e la coagulazione del sangue.",
                "Buona fonte di folati e fibre che supportano la salute cardiovascolare e la digestione.",
            ],
            "es": [
                "Excepcionalmente ricos en vitamina C: una taza aporta más del 100% de la necesidad diaria.",
                "Contienen glucosinolatos, compuestos asociados a la reducción del riesgo de cáncer.",
                "Alto contenido en vitamina K, esencial para la fortaleza ósea y la coagulación sanguínea.",
                "Buena fuente de folato y fibra que favorecen la salud cardiovascular y la digestión.",
            ],
            "fr": [
                "Exceptionnellement riches en vitamine C — une tasse couvre plus de 100 % des besoins journaliers.",
                "Contiennent des glucosinolates, des composés associés à une réduction du risque de cancer.",
                "Riches en vitamine K, essentielle pour la solidité osseuse et la coagulation sanguine.",
                "Bonne source de folate et de fibres bénéfiques pour le cœur et la digestion.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "brussels sprouts dinner"},
            "salad": {"source_id": "eatingwell", "query": "brussels sprouts salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "brussels sprouts hash breakfast"},
        },
    },
    {
        "id": "green_peas",
        "emoji": "🟢",
        "name": {"ru": "Зелёный горошек", "en": "Green peas", "it": "Piselli", "es": "Guisantes", "fr": "Petits pois"},
        "benefits": {
            "ru": [
                "Отличный растительный источник белка — около 8 г на стакан варёного горошка, поддерживает мышцы.",
                "Богаты клетчаткой, которая замедляет пищеварение, стабилизирует сахар в крови и даёт чувство сытости.",
                "Много витаминов C, K и фолиевой кислоты, важных для здоровья клеток.",
                "Содержат антиоксиданты лютеин и зеаксантин, защищающие зрение.",
            ],
            "en": [
                "Excellent plant-based protein source with around 8 g per cooked cup, supporting muscle maintenance.",
                "Rich in fiber that slows digestion, stabilizes blood sugar, and promotes satiety.",
                "High in vitamins C and K, and the B-vitamin folate essential for cell health.",
                "Contain lutein and zeaxanthin antioxidants that help protect vision.",
            ],
            "it": [
                "Ottima fonte proteica vegetale: circa 8 g per tazza cotta, a supporto del mantenimento muscolare.",
                "Ricchi di fibre che rallentano la digestione, stabilizzano la glicemia e aumentano il senso di sazietà.",
                "Elevato contenuto di vitamina C, vitamina K e folati, essenziali per la salute cellulare.",
                "Contengono luteina e zeaxantina, antiossidanti che aiutano a proteggere la vista.",
            ],
            "es": [
                "Excelente fuente proteica vegetal: unos 8 g por taza cocida, ideal para el mantenimiento muscular.",
                "Ricos en fibra que ralentiza la digestión, estabiliza el azúcar en sangre y promueve la saciedad.",
                "Alto contenido en vitaminas C y K, y folato, esenciales para la salud celular.",
                "Contienen luteína y zeaxantina, antioxidantes que ayudan a proteger la visión.",
            ],
            "fr": [
                "Excellente source de protéines végétales : environ 8 g par tasse cuite, pour maintenir la masse musculaire.",
                "Riches en fibres qui ralentissent la digestion, stabilisent la glycémie et favorisent la satiété.",
                "Riches en vitamines C et K, et en folate essentiel à la santé cellulaire.",
                "Contiennent de la lutéine et de la zéaxanthine, des antioxydants qui protègent la vue.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "green peas dinner"},
            "salad": {"source_id": "eatingwell", "query": "green peas salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "pea fritters breakfast"},
        },
    },
    {
        "id": "onion",
        "emoji": "🧅",
        "name": {"ru": "Лук", "en": "Onion", "it": "Cipolla", "es": "Cebolla", "fr": "Oignon"},
        "benefits": {
            "ru": [
                "Богат кверцетином — флавоноидом с противовоспалительными и кардиозащитными свойствами.",
                "Содержит пребиотики, питающие полезную микрофлору кишечника и поддерживающие иммунитет.",
                "Органосерные соединения лука ассоциируются со снижением артериального давления и холестерина.",
                "Мало калорий, хороший источник витамина C и витаминов группы B.",
            ],
            "en": [
                "Rich in quercetin, an antioxidant flavonoid with anti-inflammatory and heart-protective effects.",
                "Contains prebiotics that feed beneficial gut bacteria and support immune function.",
                "Organosulfur compounds in onions are associated with reduced blood pressure and cholesterol.",
                "Low in calories and a good source of vitamin C and B vitamins.",
            ],
            "it": [
                "Ricco di quercetina, un flavonoide antiossidante con effetti antinfiammatori e cardioprotettivi.",
                "Contiene prebiotici che nutrono i batteri intestinali benefici e supportano l'immunità.",
                "I composti organosolfurati della cipolla sono associati alla riduzione di pressione e colesterolo.",
                "Povero di calorie e buona fonte di vitamina C e vitamine del gruppo B.",
            ],
            "es": [
                "Rico en quercetina, un flavonoide antioxidante con efectos antiinflamatorios y cardioprotectores.",
                "Contiene prebióticos que alimentan las bacterias intestinales beneficiosas y apoyan la inmunidad.",
                "Los compuestos organosulfurados de la cebolla se asocian con la reducción de la presión arterial y el colesterol.",
                "Bajo en calorías y buena fuente de vitamina C y vitaminas del grupo B.",
            ],
            "fr": [
                "Riche en quercétine, un flavonoïde antioxydant aux effets anti-inflammatoires et cardioprotecteurs.",
                "Contient des prébiotiques qui nourrissent les bonnes bactéries intestinales et soutiennent l'immunité.",
                "Les composés organosoufrés de l'oignon sont associés à la réduction de la pression artérielle et du cholestérol.",
                "Peu calorique et bonne source de vitamine C et de vitamines B.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "caramelized onion dinner"},
            "salad": {"source_id": "eatingwell", "query": "onion salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "onion omelette breakfast"},
        },
    },
    {
        "id": "arugula",
        "emoji": "🌿",
        "name": {"ru": "Руккола", "en": "Arugula", "it": "Rucola", "es": "Rúcula", "fr": "Roquette"},
        "benefits": {
            "ru": [
                "Один из самых богатых листовых источников витамина K, необходимого для здоровья костей.",
                "Содержит глюкозинолаты и эруцин, которым в исследованиях приписывают онкопротекторные свойства.",
                "Богата нитратами, которые организм превращает в оксид азота, улучшающий кровоток.",
                "Очень мало калорий, при этом много кальция, фолиевой кислоты и бета-каротина.",
            ],
            "en": [
                "One of the richest leafy green sources of vitamin K, essential for bone health.",
                "Contains glucosinolates and erucin linked to cancer-protective properties in research.",
                "Provides nitrates that the body converts to nitric oxide, supporting healthy blood flow.",
                "Very low in calories and rich in calcium, folate, and beta-carotene.",
            ],
            "it": [
                "Tra le verdure a foglia verde, è una delle più ricche di vitamina K, essenziale per la salute delle ossa.",
                "Contiene glucosinolati ed erucina, a cui la ricerca attribuisce proprietà anticancerogene.",
                "Fornisce nitrati che l'organismo trasforma in ossido nitrico, favorendo una sana circolazione.",
                "Pochissime calorie e ricca di calcio, folati e beta-carotene.",
            ],
            "es": [
                "Una de las verduras de hoja verde más ricas en vitamina K, esencial para la salud ósea.",
                "Contiene glucosinolatos y erucina, a los que se atribuyen propiedades anticancerígenas en investigaciones.",
                "Aporta nitratos que el cuerpo convierte en óxido nítrico, favoreciendo una circulación sana.",
                "Muy baja en calorías y rica en calcio, folato y betacaroteno.",
            ],
            "fr": [
                "L'une des meilleures sources de vitamine K parmi les légumes verts feuillus, essentielle pour les os.",
                "Contient des glucosinolates et de l'érucine, auxquels la recherche attribue des propriétés anticancéreuses.",
                "Apporte des nitrates que l'organisme convertit en oxyde nitrique, favorisant une bonne circulation.",
                "Très peu calorique et riche en calcium, folate et bêta-carotène.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "arugula pasta dinner"},
            "salad": {"source_id": "eatingwell", "query": "arugula salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "arugula eggs breakfast"},
        },
    },
    {
        "id": "potato",
        "emoji": "🥔",
        "name": {"ru": "Картофель", "en": "Potato", "it": "Patata", "es": "Patata", "fr": "Pomme de terre"},
        "benefits": {
            "ru": [
                "Отличный источник калия — больше, чем в банане, — поддерживает здоровье сердца и давление.",
                "Содержит резистентный крахмал (особенно в охлаждённом виде), питающий полезную микрофлору кишечника.",
                "Хороший источник витаминов C, B6 и ряда витаминов группы B, важных для энергетического обмена.",
                "Не содержит жира, а клетчатка и вода обеспечивают длительное чувство сытости.",
            ],
            "en": [
                "Excellent source of potassium — more per serving than a banana — supporting heart health and blood pressure.",
                "Contains resistant starch (especially when cooled) that feeds beneficial gut bacteria.",
                "Good source of vitamin C, B6, and several B vitamins essential for energy metabolism.",
                "Naturally fat-free and satisfying due to high fiber and water content.",
            ],
            "it": [
                "Ottima fonte di potassio — più di una banana per porzione — a supporto della salute cardiaca e della pressione.",
                "Contiene amido resistente (soprattutto da freddo) che nutre i batteri intestinali benefici.",
                "Buona fonte di vitamina C, B6 e altre vitamine B essenziali per il metabolismo energetico.",
                "Naturalmente privo di grassi e saziante grazie all'alto contenuto di fibre e acqua.",
            ],
            "es": [
                "Excelente fuente de potasio — más por porción que un plátano — que apoya la salud cardíaca y la presión.",
                "Contiene almidón resistente (especialmente en frío) que alimenta las bacterias intestinales beneficiosas.",
                "Buena fuente de vitaminas C, B6 y varias vitaminas B esenciales para el metabolismo energético.",
                "Naturalmente sin grasa y saciante gracias a su alto contenido en fibra y agua.",
            ],
            "fr": [
                "Excellente source de potassium — plus par portion qu'une banane — soutenant la santé cardiaque et la pression.",
                "Contient de l'amidon résistant (surtout refroidi) qui nourrit les bonnes bactéries intestinales.",
                "Bonne source de vitamines C, B6 et plusieurs vitamines B essentielles au métabolisme énergétique.",
                "Naturellement sans matières grasses et rassasiant grâce à sa haute teneur en fibres et en eau.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "potato dinner"},
            "salad": {"source_id": "eatingwell", "query": "potato salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "potato hash breakfast"},
        },
    },
    {
        "id": "raspberry",
        "emoji": "🍓",
        "name": {"ru": "Малина", "en": "Raspberry", "it": "Lampone", "es": "Frambuesa", "fr": "Framboise"},
        "benefits": {
            "ru": [
                "Один из рекордсменов по клетчатке среди фруктов — 8 г на стакан, поддерживает пищеварение и сытость.",
                "Богаты антоцианами и эллаговой кислотой — антиоксидантами, снижающими воспаление.",
                "Низкий гликемический индекс — отличный выбор для контроля уровня сахара в крови.",
                "Хороший источник витамина C и марганца для иммунитета и здоровья костей.",
            ],
            "en": [
                "Among the highest-fiber fruits with 8 g per cup, supporting digestion and satiety.",
                "Packed with anthocyanins and ellagic acid — antioxidants linked to reduced inflammation.",
                "Low glycemic index makes them a smart choice for blood sugar management.",
                "Good source of vitamin C and manganese supporting immune function and bone health.",
            ],
            "it": [
                "Tra i frutti più ricchi di fibre: 8 g per tazza, a supporto della digestione e del senso di sazietà.",
                "Ricchi di antociani e acido ellagico, antiossidanti che riducono l'infiammazione.",
                "Basso indice glicemico: scelta intelligente per il controllo della glicemia.",
                "Buona fonte di vitamina C e manganese per l'immunità e la salute delle ossa.",
            ],
            "es": [
                "Entre las frutas más ricas en fibra: 8 g por taza, favoreciendo la digestión y la saciedad.",
                "Ricas en antocianinas y ácido elágico, antioxidantes que reducen la inflamación.",
                "Bajo índice glucémico, ideal para el control del azúcar en sangre.",
                "Buena fuente de vitamina C y manganeso para la inmunidad y la salud ósea.",
            ],
            "fr": [
                "Parmi les fruits les plus riches en fibres : 8 g par tasse, favorisant la digestion et la satiété.",
                "Riches en anthocyanes et en acide ellagique, des antioxydants qui réduisent l'inflammation.",
                "Faible indice glycémique, idéal pour la gestion de la glycémie.",
                "Bonne source de vitamine C et de manganèse pour l'immunité et la santé osseuse.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "raspberry sauce chicken"},
            "salad": {"source_id": "eatingwell", "query": "raspberry salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "raspberry breakfast recipes"},
        },
    },
    {
        "id": "blackberry",
        "emoji": "🫐",
        "name": {"ru": "Ежевика", "en": "Blackberry", "it": "Mora", "es": "Mora", "fr": "Mûre"},
        "benefits": {
            "ru": [
                "Богата антоцианами, которые борются с окислительным стрессом и поддерживают здоровье мозга.",
                "Много клетчатки — около 7 г на стакан — для здорового пищеварения.",
                "Отличный источник витамина C: покрывает значительную часть суточной нормы.",
                "Содержит витамин K и марганец, важные для костного обмена и заживления ран.",
            ],
            "en": [
                "Rich in anthocyanins that combat oxidative stress and support brain health.",
                "High fiber content — about 7 g per cup — promoting healthy digestion.",
                "Excellent source of vitamin C providing a significant portion of the daily requirement.",
                "Contains vitamin K and manganese important for bone metabolism and wound healing.",
            ],
            "it": [
                "Ricca di antociani che contrastano lo stress ossidativo e supportano la salute cerebrale.",
                "Alto contenuto di fibre — circa 7 g per tazza — per una digestione sana.",
                "Ottima fonte di vitamina C che copre una parte significativa del fabbisogno giornaliero.",
                "Contiene vitamina K e manganese importanti per il metabolismo osseo e la cicatrizzazione.",
            ],
            "es": [
                "Rica en antocianinas que combaten el estrés oxidativo y apoyan la salud cerebral.",
                "Alto contenido en fibra — unos 7 g por taza — para una digestión saludable.",
                "Excelente fuente de vitamina C que cubre una parte significativa de la necesidad diaria.",
                "Contiene vitamina K y manganeso importantes para el metabolismo óseo y la cicatrización.",
            ],
            "fr": [
                "Riche en anthocyanes qui combattent le stress oxydatif et soutiennent la santé cérébrale.",
                "Haute teneur en fibres — environ 7 g par tasse — pour une digestion saine.",
                "Excellente source de vitamine C couvrant une part significative des besoins journaliers.",
                "Contient de la vitamine K et du manganèse importants pour le métabolisme osseux et la cicatrisation.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "blackberry sauce recipes"},
            "salad": {"source_id": "eatingwell", "query": "blackberry salad"},
            "breakfast": {"source_id": "eatingwell", "query": "blackberry breakfast"},
        },
    },
    {
        "id": "pomegranate",
        "emoji": "🍎",
        "name": {"ru": "Гранат", "en": "Pomegranate", "it": "Melograno", "es": "Granada", "fr": "Grenade"},
        "benefits": {
            "ru": [
                "Содержит пуникалагины и пуниковую кислоту — уникально мощные антиоксиданты с противовоспалительным действием.",
                "Клинические исследования показывают, что сок граната может снижать систолическое давление.",
                "Богат эллаговой кислотой, полезной для кишечника и изученной на предмет онкопротекторных свойств.",
                "Хороший источник клетчатки, витаминов C, K и фолиевой кислоты.",
            ],
            "en": [
                "Contains punicalagins and punicic acid, uniquely potent antioxidants that reduce inflammation.",
                "Clinical studies show pomegranate juice may lower systolic blood pressure.",
                "Rich in ellagic acid that supports gut health and has been studied for cancer-protective properties.",
                "Good source of fiber, vitamin C, vitamin K, and folate.",
            ],
            "it": [
                "Contiene punicalagine e acido punico, antiossidanti di potenza unica che riducono l'infiammazione.",
                "Studi clinici mostrano che il succo di melograno può abbassare la pressione sistolica.",
                "Ricco di acido ellagico a supporto della salute intestinale e studiato per proprietà anticancro.",
                "Buona fonte di fibre, vitamina C, vitamina K e folati.",
            ],
            "es": [
                "Contiene punicalagins y ácido púnico, antioxidantes únicamente potentes que reducen la inflamación.",
                "Estudios clínicos muestran que el zumo de granada puede reducir la presión sistólica.",
                "Rico en ácido elágico, beneficioso para la salud intestinal y estudiado por sus propiedades anticancerígenas.",
                "Buena fuente de fibra, vitaminas C y K, y folato.",
            ],
            "fr": [
                "Contient des punicalagins et de l'acide punicique, des antioxydants d'une puissance unique qui réduisent l'inflammation.",
                "Des études cliniques montrent que le jus de grenade peut abaisser la pression systolique.",
                "Riche en acide ellagique, bénéfique pour la santé intestinale et étudié pour ses propriétés anticancéreuses.",
                "Bonne source de fibres, de vitamines C et K, et de folate.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "pomegranate chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "pomegranate salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "pomegranate breakfast recipes"},
        },
    },
    {
        "id": "kiwi",
        "emoji": "🥝",
        "name": {"ru": "Киви", "en": "Kiwi", "it": "Kiwi", "es": "Kiwi", "fr": "Kiwi"},
        "benefits": {
            "ru": [
                "Рекордное содержание витамина C — один плод даёт около 70 мг, что превышает суточную норму.",
                "Содержит актинидин — уникальный фермент, значительно улучшающий переваривание белков.",
                "Богат витамином K, поддерживающим здоровье костей и свёртываемость крови.",
                "Исследования показывают, что регулярное употребление улучшает качество сна, повышая уровень серотонина.",
            ],
            "en": [
                "Outstanding vitamin C content — one kiwi provides about 70 mg, exceeding the daily requirement.",
                "Contains actinidin, a unique enzyme that significantly improves protein digestion.",
                "Rich in vitamin K supporting bone health and blood coagulation.",
                "Studies show regular consumption improves sleep quality by raising serotonin levels.",
            ],
            "it": [
                "Contenuto eccezionale di vitamina C: un kiwi fornisce circa 70 mg, superando il fabbisogno giornaliero.",
                "Contiene actinidina, un enzima unico che migliora significativamente la digestione delle proteine.",
                "Ricco di vitamina K a supporto della salute ossea e della coagulazione.",
                "Studi mostrano che il consumo regolare migliora la qualità del sonno aumentando i livelli di serotonina.",
            ],
            "es": [
                "Contenido excepcional de vitamina C: un kiwi aporta unos 70 mg, superando la necesidad diaria.",
                "Contiene actinidina, una enzima única que mejora significativamente la digestión de proteínas.",
                "Rico en vitamina K que apoya la salud ósea y la coagulación.",
                "Estudios muestran que el consumo regular mejora la calidad del sueño al elevar los niveles de serotonina.",
            ],
            "fr": [
                "Teneur exceptionnelle en vitamine C : un kiwi apporte environ 70 mg, dépassant les besoins journaliers.",
                "Contient de l'actinidine, une enzyme unique qui améliore considérablement la digestion des protéines.",
                "Riche en vitamine K soutenant la santé osseuse et la coagulation.",
                "Des études montrent que sa consommation régulière améliore la qualité du sommeil en élevant les niveaux de sérotonine.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "kiwi chicken salsa dinner"},
            "salad": {"source_id": "eatingwell", "query": "kiwi fruit salad"},
            "breakfast": {"source_id": "eatingwell", "query": "kiwi breakfast recipes"},
        },
    },
    {
        "id": "mango",
        "emoji": "🥭",
        "name": {"ru": "Манго", "en": "Mango", "it": "Mango", "es": "Mango", "fr": "Mangue"},
        "benefits": {
            "ru": [
                "Исключительно богат витамином C — одна чашка покрывает около 67% суточной нормы.",
                "Много бета-каротина, который организм превращает в витамин A для иммунитета и здоровья глаз.",
                "Содержит мангиферин — полифенол с мощными антиоксидантными и противовоспалительными свойствами.",
                "Хороший источник фолиевой кислоты, клетчатки и меди, полезных для сердца и энергетического обмена.",
            ],
            "en": [
                "Exceptionally rich in vitamin C — one cup provides about 67% of the daily requirement.",
                "High in beta-carotene, which the body converts to vitamin A for immune defense and eye health.",
                "Contains mangiferin, a polyphenol with potent antioxidant and anti-inflammatory properties.",
                "Good source of folate, fiber, and copper that support heart health and energy metabolism.",
            ],
            "it": [
                "Eccezionalmente ricco di vitamina C: una tazza copre circa il 67% del fabbisogno giornaliero.",
                "Alto contenuto di beta-carotene, che l'organismo trasforma in vitamina A per le difese immunitarie e la vista.",
                "Contiene mangiferin, un polifenolo con potenti proprietà antiossidanti e antinfiammatorie.",
                "Buona fonte di folati, fibre e rame a supporto della salute cardiovascolare e del metabolismo energetico.",
            ],
            "es": [
                "Excepcionalmente rico en vitamina C: una taza cubre el 67% de la necesidad diaria.",
                "Alto en betacaroteno, que el cuerpo convierte en vitamina A para la inmunidad y la salud ocular.",
                "Contiene mangiferin, un polifenol con potentes propiedades antioxidantes y antiinflamatorias.",
                "Buena fuente de folato, fibra y cobre para la salud cardiovascular y el metabolismo energético.",
            ],
            "fr": [
                "Exceptionnellement riche en vitamine C : une tasse couvre environ 67 % des besoins journaliers.",
                "Riche en bêta-carotène, que l'organisme convertit en vitamine A pour l'immunité et la santé oculaire.",
                "Contient de la mangifèrine, un polyphénol aux puissantes propriétés antioxydantes et anti-inflammatoires.",
                "Bonne source de folate, de fibres et de cuivre pour la santé cardiovasculaire et le métabolisme énergétique.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "mango chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "mango salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "mango breakfast recipes"},
        },
    },
    {
        "id": "pineapple",
        "emoji": "🍍",
        "name": {"ru": "Ананас", "en": "Pineapple", "it": "Ananas", "es": "Piña", "fr": "Ananas"},
        "benefits": {
            "ru": [
                "Содержит бромелайн — уникальный ферментный комплекс, улучшающий переваривание белков и снижающий воспаление.",
                "Богат витамином C — одна чашка покрывает около 80% суточной нормы.",
                "Хороший источник марганца, необходимого для формирования костей и активности антиоксидантных ферментов.",
                "Содержит клетчатку и витамины группы B, поддерживающие выработку энергии и здоровье кишечника.",
            ],
            "en": [
                "Contains bromelain, a unique enzyme complex that aids protein digestion and reduces inflammation.",
                "Rich in vitamin C providing about 80% of the daily requirement per cup.",
                "Good source of manganese essential for bone formation and antioxidant enzyme activity.",
                "Provides dietary fiber and B vitamins supporting energy production and digestive health.",
            ],
            "it": [
                "Contiene bromelina, un complesso enzimatico unico che aiuta la digestione delle proteine e riduce l'infiammazione.",
                "Ricco di vitamina C: una tazza copre circa l'80% del fabbisogno giornaliero.",
                "Buona fonte di manganese essenziale per la formazione ossea e l'attività degli enzimi antiossidanti.",
                "Apporta fibre e vitamine B a supporto della produzione energetica e della salute digestiva.",
            ],
            "es": [
                "Contiene bromelina, un complejo enzimático único que ayuda a digerir proteínas y reduce la inflamación.",
                "Rico en vitamina C: una taza cubre el 80% de la necesidad diaria.",
                "Buena fuente de manganeso esencial para la formación ósea y la actividad de enzimas antioxidantes.",
                "Aporta fibra y vitaminas B para la producción de energía y la salud digestiva.",
            ],
            "fr": [
                "Contient de la broméline, un complexe enzymatique unique qui favorise la digestion des protéines et réduit l'inflammation.",
                "Riche en vitamine C : une tasse couvre environ 80 % des besoins journaliers.",
                "Bonne source de manganèse essentiel à la formation osseuse et à l'activité des enzymes antioxydantes.",
                "Apporte des fibres et des vitamines B pour la production d'énergie et la santé digestive.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "pineapple chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "pineapple salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "pineapple breakfast recipes"},
        },
    },
    {
        "id": "grapes",
        "emoji": "🍇",
        "name": {"ru": "Виноград", "en": "Grapes", "it": "Uva", "es": "Uvas", "fr": "Raisins"},
        "benefits": {
            "ru": [
                "Богаты ресвератролом — полифенолом, ассоциированным с защитой сердца и противовоспалительным действием.",
                "Содержат антоцианы и другие антиоксиданты, снижающие окислительный стресс.",
                "Хороший источник витамина K и калия, поддерживающих плотность костей и артериальное давление.",
                "Дают природные сахара вместе с клетчаткой и водой для стабильной энергии без резких скачков.",
            ],
            "en": [
                "Rich in resveratrol, a polyphenol associated with heart protection and anti-inflammatory effects.",
                "Contain anthocyanins and other antioxidants shown to reduce oxidative stress.",
                "Good source of vitamin K and potassium supporting bone density and blood pressure.",
                "Provide natural sugars along with fiber and water for sustained energy without crashes.",
            ],
            "it": [
                "Ricchi di resveratrolo, un polifenolo associato alla protezione cardiovascolare e agli effetti antinfiammatori.",
                "Contengono antociani e altri antiossidanti che riducono lo stress ossidativo.",
                "Buona fonte di vitamina K e potassio a supporto della densità ossea e della pressione arteriosa.",
                "Forniscono zuccheri naturali insieme a fibre e acqua per un'energia stabile e prolungata.",
            ],
            "es": [
                "Ricos en resveratrol, un polifenol asociado con la protección cardíaca y efectos antiinflamatorios.",
                "Contienen antocianinas y otros antioxidantes que reducen el estrés oxidativo.",
                "Buena fuente de vitamina K y potasio para la densidad ósea y la presión arterial.",
                "Aportan azúcares naturales junto con fibra y agua para una energía estable y sostenida.",
            ],
            "fr": [
                "Riches en resvératrol, un polyphénol associé à la protection cardiaque et aux effets anti-inflammatoires.",
                "Contiennent des anthocyanes et d'autres antioxydants qui réduisent le stress oxydatif.",
                "Bonne source de vitamine K et de potassium pour la densité osseuse et la pression artérielle.",
                "Fournissent des sucres naturels avec des fibres et de l'eau pour une énergie stable et durable.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "grape chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "grape salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "grape breakfast recipes"},
        },
    },
    {
        "id": "pear",
        "emoji": "🍐",
        "name": {"ru": "Груша", "en": "Pear", "it": "Pera", "es": "Pera", "fr": "Poire"},
        "benefits": {
            "ru": [
                "Отличный источник пищевых волокон — одна средняя груша даёт около 5,5 г клетчатки для здоровья кишечника.",
                "Богата витамином C и медью, выступающими антиоксидантами и защищающими клетки от повреждений.",
                "Содержит флавоноиды, ассоциированные со снижением риска диабета 2 типа и сердечно-сосудистых заболеваний.",
                "Фрукт с низким гликемическим индексом: медленно высвобождает энергию и стабилизирует уровень сахара.",
            ],
            "en": [
                "Excellent source of dietary fiber — one medium pear provides about 5.5 g supporting gut health.",
                "Rich in vitamin C and copper that act as antioxidants protecting cells from damage.",
                "Contains flavonoids linked to reduced risk of type 2 diabetes and heart disease.",
                "Low glycemic index fruit that releases energy slowly, helping to maintain stable blood sugar.",
            ],
            "it": [
                "Ottima fonte di fibre: una pera media fornisce circa 5,5 g, a supporto della salute intestinale.",
                "Ricca di vitamina C e rame, antiossidanti che proteggono le cellule dai danni.",
                "Contiene flavonoidi associati a un ridotto rischio di diabete di tipo 2 e malattie cardiache.",
                "Frutto a basso indice glicemico che rilascia energia lentamente, mantenendo stabile la glicemia.",
            ],
            "es": [
                "Excelente fuente de fibra dietética: una pera mediana aporta unos 5,5 g para la salud intestinal.",
                "Rica en vitamina C y cobre, antioxidantes que protegen las células del daño.",
                "Contiene flavonoides asociados con menor riesgo de diabetes tipo 2 y enfermedades cardíacas.",
                "Fruta de bajo índice glucémico que libera energía lentamente, ayudando a mantener estable el azúcar en sangre.",
            ],
            "fr": [
                "Excellente source de fibres : une poire moyenne fournit environ 5,5 g, bénéfiques pour la santé intestinale.",
                "Riche en vitamine C et en cuivre, des antioxydants qui protègent les cellules des dommages.",
                "Contient des flavonoïdes associés à un risque réduit de diabète de type 2 et de maladies cardiaques.",
                "Fruit à faible indice glycémique qui libère l'énergie lentement, aidant à stabiliser la glycémie.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "pear chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "pear salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "pear breakfast recipes"},
        },
    },
    {
        "id": "peach",
        "emoji": "🍑",
        "name": {"ru": "Персик", "en": "Peach", "it": "Pesca", "es": "Melocotón", "fr": "Pêche"},
        "benefits": {
            "ru": [
                "Хороший источник витаминов C и A, поддерживающих иммунитет и здоровую кожу.",
                "Содержит хлорогеновую кислоту — антиоксидант с противовоспалительными и метаболическими свойствами.",
                "Содержит клетчатку и калий, полезные для сердца и нормализации давления.",
                "Мало калорий и натуральная сладость — отличный выбор для контроля веса.",
            ],
            "en": [
                "Good source of vitamins C and A supporting immune function and healthy skin.",
                "Contains chlorogenic acid, an antioxidant associated with anti-inflammatory and metabolic benefits.",
                "Provides dietary fiber and potassium beneficial for heart health and blood pressure.",
                "Low in calories and naturally sweet, making it a satisfying choice for weight management.",
            ],
            "it": [
                "Buona fonte di vitamina C e A, a supporto dell'immunità e di una pelle sana.",
                "Contiene acido clorogenico, un antiossidante con benefici antinfiammatori e metabolici.",
                "Fornisce fibre e potassio benefici per la salute cardiovascolare e la pressione arteriosa.",
                "Povera di calorie e naturalmente dolce: scelta soddisfacente per la gestione del peso.",
            ],
            "es": [
                "Buena fuente de vitaminas C y A que apoyan la inmunidad y la salud de la piel.",
                "Contiene ácido clorogénico, un antioxidante con beneficios antiinflamatorios y metabólicos.",
                "Aporta fibra y potasio beneficiosos para la salud cardiovascular y la presión arterial.",
                "Baja en calorías y naturalmente dulce, perfecta para el control de peso.",
            ],
            "fr": [
                "Bonne source de vitamines C et A soutenant l'immunité et la santé de la peau.",
                "Contient de l'acide chlorogénique, un antioxydant aux bénéfices anti-inflammatoires et métaboliques.",
                "Apporte des fibres et du potassium bénéfiques pour la santé cardiovasculaire et la pression artérielle.",
                "Peu calorique et naturellement sucrée, c'est un choix satisfaisant pour la gestion du poids.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "peach chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "peach salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "peach breakfast recipes"},
        },
    },
    {
        "id": "grapefruit",
        "emoji": "🍊",
        "name": {"ru": "Грейпфрут", "en": "Grapefruit", "it": "Pompelmo", "es": "Pomelo", "fr": "Pamplemousse"},
        "benefits": {
            "ru": [
                "Отличный источник витамина C — половина грейпфрута покрывает около 64% суточной нормы.",
                "Содержит ликопин и бета-каротин — антиоксиданты, защищающие клетки от повреждений.",
                "Исследования связывают регулярное употребление со снижением давления и уровня «плохого» холестерина.",
                "Высокое содержание воды и клетчатки способствует насыщению и контролю веса.",
            ],
            "en": [
                "Excellent source of vitamin C — half a grapefruit provides about 64% of the daily requirement.",
                "Contains lycopene and beta-carotene, antioxidants that help protect against cell damage.",
                "Studies suggest regular consumption is associated with reduced blood pressure and LDL cholesterol.",
                "High water content and fiber promote satiety and support healthy weight management.",
            ],
            "it": [
                "Ottima fonte di vitamina C: mezzo pompelmo copre circa il 64% del fabbisogno giornaliero.",
                "Contiene licopene e beta-carotene, antiossidanti che proteggono le cellule dai danni.",
                "Studi suggeriscono che il consumo regolare è associato a una riduzione della pressione e del colesterolo LDL.",
                "L'alto contenuto di acqua e fibre favorisce il senso di sazietà e la gestione del peso.",
            ],
            "es": [
                "Excelente fuente de vitamina C: medio pomelo cubre el 64% de la necesidad diaria.",
                "Contiene licopeno y betacaroteno, antioxidantes que protegen las células del daño.",
                "Estudios asocian el consumo regular con la reducción de la presión arterial y el colesterol LDL.",
                "Su alto contenido en agua y fibra favorece la saciedad y el control del peso.",
            ],
            "fr": [
                "Excellente source de vitamine C : un demi pamplemousse couvre environ 64 % des besoins journaliers.",
                "Contient du lycopène et du bêta-carotène, des antioxydants qui protègent les cellules.",
                "Des études associent sa consommation régulière à une réduction de la pression artérielle et du cholestérol LDL.",
                "Sa haute teneur en eau et en fibres favorise la satiété et la gestion du poids.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "grapefruit salmon dinner"},
            "salad": {"source_id": "eatingwell", "query": "grapefruit salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "grapefruit breakfast"},
        },
    },
    {
        "id": "lemon",
        "emoji": "🍋",
        "name": {"ru": "Лимон", "en": "Lemon", "it": "Limone", "es": "Limón", "fr": "Citron"},
        "benefits": {
            "ru": [
                "Выдающийся источник витамина C — один лимон даёт около 50 мг, укрепляя иммунитет.",
                "Содержит д-лимонен — растительное соединение с противовоспалительными и возможными онкопротекторными свойствами.",
                "Лимонная кислота может предотвращать образование камней в почках, повышая уровень цитрата в моче.",
                "Флавоноиды, включая гесперидин, поддерживают здоровье сосудов и снижают воспаление.",
            ],
            "en": [
                "Outstanding source of vitamin C — one lemon provides about 50 mg, boosting immunity.",
                "Contains d-limonene, a plant compound with anti-inflammatory and potential cancer-protective properties.",
                "Citric acid in lemons may help prevent kidney stones by increasing urine citrate levels.",
                "Flavonoids including hesperidin support blood vessel health and reduce inflammation.",
            ],
            "it": [
                "Fonte straordinaria di vitamina C: un limone fornisce circa 50 mg, potenziando l'immunità.",
                "Contiene d-limonene, un composto vegetale con proprietà antinfiammatorie e potenzialmente anticancro.",
                "L'acido citrico può aiutare a prevenire i calcoli renali aumentando il citrato nelle urine.",
                "I flavonoidi, inclusa l'esperidina, supportano la salute dei vasi sanguigni e riducono l'infiammazione.",
            ],
            "es": [
                "Fuente excepcional de vitamina C: un limón aporta unos 50 mg, reforzando la inmunidad.",
                "Contiene d-limoneno, un compuesto vegetal con propiedades antiinflamatorias y potencialmente anticancerígenas.",
                "El ácido cítrico puede ayudar a prevenir los cálculos renales aumentando el citrato urinario.",
                "Flavonoides como la hesperidina apoyan la salud de los vasos sanguíneos y reducen la inflamación.",
            ],
            "fr": [
                "Source exceptionnelle de vitamine C : un citron apporte environ 50 mg, renforçant l'immunité.",
                "Contient du d-limonène, un composé végétal aux propriétés anti-inflammatoires et potentiellement anticancéreuses.",
                "L'acide citrique peut aider à prévenir les calculs rénaux en augmentant le citrate urinaire.",
                "Les flavonoïdes dont l'hespéridine soutiennent la santé vasculaire et réduisent l'inflammation.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "lemon chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "lemon dressing salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "lemon breakfast recipes"},
        },
    },
    {
        "id": "watermelon",
        "emoji": "🍉",
        "name": {"ru": "Арбуз", "en": "Watermelon", "it": "Anguria", "es": "Sandía", "fr": "Pastèque"},
        "benefits": {
            "ru": [
                "Около 92% воды — один из самых гидратирующих продуктов.",
                "Богат ликопином — мощным антиоксидантом, ассоциированным со снижением риска сердечно-сосудистых заболеваний и некоторых видов рака.",
                "Содержит цитруллин — аминокислоту, которая может ускорять восстановление после тренировок и снижать боль в мышцах.",
                "Мало калорий, при этом содержит витамины A и C, а также антиоксидант бета-каротин.",
            ],
            "en": [
                "About 92% water, making it one of the most hydrating foods available.",
                "Rich in lycopene, a powerful antioxidant linked to reduced risk of heart disease and certain cancers.",
                "Contains citrulline, an amino acid that may improve exercise recovery and reduce muscle soreness.",
                "Low in calories while providing vitamins A and C and the antioxidant beta-carotene.",
            ],
            "it": [
                "Circa il 92% di acqua: uno degli alimenti più idratanti in assoluto.",
                "Ricco di licopene, un potente antiossidante associato a un ridotto rischio di malattie cardiache e alcuni tumori.",
                "Contiene citrullina, un aminoacido che può migliorare il recupero dall'esercizio e ridurre i dolori muscolari.",
                "Povero di calorie pur fornendo vitamina A, vitamina C e il beta-carotene antiossidante.",
            ],
            "es": [
                "Aproximadamente el 92% es agua, convirtiéndola en uno de los alimentos más hidratantes.",
                "Rica en licopeno, un potente antioxidante asociado con menor riesgo de enfermedades cardíacas y ciertos cánceres.",
                "Contiene citrulina, un aminoácido que puede mejorar la recuperación muscular tras el ejercicio.",
                "Baja en calorías y aporta vitaminas A y C, además del antioxidante betacaroteno.",
            ],
            "fr": [
                "Environ 92 % d'eau, ce qui en fait l'un des aliments les plus hydratants.",
                "Riche en lycopène, un puissant antioxydant associé à un risque réduit de maladies cardiaques et de certains cancers.",
                "Contient de la citrulline, un acide aminé qui peut améliorer la récupération musculaire après l'exercice.",
                "Peu calorique tout en apportant des vitamines A et C et du bêta-carotène antioxydant.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "watermelon feta salad dinner"},
            "salad": {"source_id": "eatingwell", "query": "watermelon salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "watermelon breakfast smoothie"},
        },
    },
    {
        "id": "melon",
        "emoji": "🍈",
        "name": {"ru": "Дыня", "en": "Melon", "it": "Melone", "es": "Melón", "fr": "Melon"},
        "benefits": {
            "ru": [
                "Богата бета-каротином и витамином A, необходимыми для здоровья глаз и иммунной защиты.",
                "Отличный источник витамина C — одна порция покрывает значительную часть суточной нормы.",
                "Высокое содержание воды — около 90% — поддерживает гидратацию при минимуме калорий.",
                "Содержит калий и витамины группы B, поддерживающие работу сердца и энергетический обмен.",
            ],
            "en": [
                "High in beta-carotene and vitamin A, essential for eye health and immune defense.",
                "Excellent source of vitamin C providing a significant portion of daily needs per serving.",
                "High water content — about 90% — supports hydration and is very low in calories.",
                "Contains potassium and B vitamins supporting heart function and energy metabolism.",
            ],
            "it": [
                "Ricco di beta-carotene e vitamina A, essenziali per la salute degli occhi e le difese immunitarie.",
                "Ottima fonte di vitamina C che copre una parte significativa del fabbisogno giornaliero per porzione.",
                "Alto contenuto d'acqua — circa il 90% — idratante e pochissimo calorico.",
                "Contiene potassio e vitamine B a supporto della funzione cardiaca e del metabolismo energetico.",
            ],
            "es": [
                "Rico en betacaroteno y vitamina A, esenciales para la salud ocular y las defensas inmunitarias.",
                "Excelente fuente de vitamina C que cubre una parte significativa de las necesidades diarias por porción.",
                "Alto contenido en agua — alrededor del 90% — hidratante y muy bajo en calorías.",
                "Contiene potasio y vitaminas B para la función cardíaca y el metabolismo energético.",
            ],
            "fr": [
                "Riche en bêta-carotène et en vitamine A, essentiels pour la santé oculaire et les défenses immunitaires.",
                "Excellente source de vitamine C couvrant une part significative des besoins journaliers par portion.",
                "Haute teneur en eau — environ 90 % — hydratant et très peu calorique.",
                "Contient du potassium et des vitamines B pour la fonction cardiaque et le métabolisme énergétique.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "melon prosciutto starter"},
            "salad": {"source_id": "eatingwell", "query": "melon salad"},
            "breakfast": {"source_id": "eatingwell", "query": "melon breakfast recipes"},
        },
    },
    {
        "id": "fig",
        "emoji": "🟣",
        "name": {"ru": "Инжир", "en": "Fig", "it": "Fico", "es": "Higo", "fr": "Figue"},
        "benefits": {
            "ru": [
                "Один из лучших фруктовых источников кальция, поддерживающего плотность костей.",
                "Богат пребиотиками и клетчаткой, питающими кишечную микрофлору и нормализующими пищеварение.",
                "Содержит полифенолы, включая хлорогеновую кислоту, связанные с регуляцией уровня сахара.",
                "Хороший источник калия, магния и витаминов группы B для сердца и нервной системы.",
            ],
            "en": [
                "One of the richest fruit sources of calcium, supporting bone density.",
                "High in prebiotics and dietary fiber that nourish gut bacteria and support regular digestion.",
                "Contains polyphenols including chlorogenic acid linked to blood sugar regulation.",
                "Good source of potassium, magnesium, and B vitamins supporting heart and nerve function.",
            ],
            "it": [
                "Una delle fonti di calcio più ricche tra i frutti, a supporto della densità ossea.",
                "Ricco di prebiotici e fibre che nutrono i batteri intestinali e favoriscono una digestione regolare.",
                "Contiene polifenoli incluso l'acido clorogenico, associato alla regolazione della glicemia.",
                "Buona fonte di potassio, magnesio e vitamine B per il cuore e la funzione nervosa.",
            ],
            "es": [
                "Una de las frutas más ricas en calcio, apoyando la densidad ósea.",
                "Rico en prebióticos y fibra que nutren las bacterias intestinales y favorecen una digestión regular.",
                "Contiene polifenoles como el ácido clorogénico, asociado con la regulación del azúcar en sangre.",
                "Buena fuente de potasio, magnesio y vitaminas B para el corazón y el sistema nervioso.",
            ],
            "fr": [
                "L'une des meilleures sources de calcium parmi les fruits, soutenant la densité osseuse.",
                "Riche en prébiotiques et en fibres qui nourrissent les bactéries intestinales et favorisent une digestion régulière.",
                "Contient des polyphénols dont l'acide chlorogénique, associé à la régulation de la glycémie.",
                "Bonne source de potassium, de magnésium et de vitamines B pour le cœur et le système nerveux.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "fig baked recipes"},
            "salad": {"source_id": "eatingwell", "query": "fig salad"},
            "breakfast": {"source_id": "eatingwell", "query": "fig breakfast recipes"},
        },
    },
    {
        "id": "beans",
        "emoji": "🫘",
        "name": {"ru": "Фасоль", "en": "Beans", "it": "Fagioli", "es": "Judías", "fr": "Haricots"},
        "benefits": {
            "ru": [
                "Отличный растительный источник белка — около 15 г на стакан варёной фасоли для поддержания мышц.",
                "Очень много растворимой клетчатки, снижающей «плохой» холестерин и стабилизирующей сахар в крови.",
                "Богата железом, фолиевой кислотой и магнием для выработки энергии и образования эритроцитов.",
                "Исследования Гарварда связывают регулярное употребление фасоли со снижением риска болезней сердца и диабета 2 типа.",
            ],
            "en": [
                "Excellent plant-based protein source with about 15 g per cooked cup, supporting muscle health.",
                "Very high in soluble fiber that lowers LDL cholesterol and stabilizes blood sugar.",
                "Rich in iron, folate, and magnesium essential for energy production and red blood cell formation.",
                "Harvard research links regular bean consumption to reduced risk of heart disease and type 2 diabetes.",
            ],
            "it": [
                "Ottima fonte proteica vegetale: circa 15 g per tazza cotta, a supporto della salute muscolare.",
                "Molto ricca di fibre solubili che abbassano il colesterolo LDL e stabilizzano la glicemia.",
                "Ricca di ferro, folati e magnesio essenziali per la produzione di energia e la formazione dei globuli rossi.",
                "La ricerca di Harvard associa il consumo regolare di fagioli a un ridotto rischio di malattie cardiache e diabete di tipo 2.",
            ],
            "es": [
                "Excelente fuente proteica vegetal: unos 15 g por taza cocida para mantener la salud muscular.",
                "Muy rica en fibra soluble que reduce el colesterol LDL y estabiliza el azúcar en sangre.",
                "Rica en hierro, folato y magnesio esenciales para la producción de energía y la formación de glóbulos rojos.",
                "La investigación de Harvard asocia el consumo regular de judías con menor riesgo de enfermedades cardíacas y diabetes tipo 2.",
            ],
            "fr": [
                "Excellente source de protéines végétales : environ 15 g par tasse cuite, pour soutenir la santé musculaire.",
                "Très riche en fibres solubles qui abaissent le cholestérol LDL et stabilisent la glycémie.",
                "Riche en fer, folate et magnésium essentiels à la production d'énergie et à la formation des globules rouges.",
                "Des recherches de Harvard associent la consommation régulière de haricots à un risque réduit de maladies cardiaques et de diabète de type 2.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "beans dinner recipes"},
            "salad": {"source_id": "eatingwell", "query": "bean salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "bean breakfast recipes"},
        },
    },
    {
        "id": "black_beans",
        "emoji": "🫘",
        "name": {"ru": "Чёрная фасоль", "en": "Black beans", "it": "Fagioli neri", "es": "Frijoles negros", "fr": "Haricots noirs"},
        "benefits": {
            "ru": [
                "Исключительно богаты антоцианами — теми же антиоксидантами, что и в чернике, защищающими клетки.",
                "Много резистентного крахмала и растворимой клетчатки, питающих полезную микрофлору и улучшающих чувствительность к инсулину.",
                "Выдающийся источник фолиевой кислоты — одна чашка покрывает около 64% суточной нормы.",
                "Железо, цинк и магний поддерживают энергию, иммунитет и восстановление мышц.",
            ],
            "en": [
                "Exceptionally rich in anthocyanins, the same antioxidants found in blueberries, protecting cells.",
                "High in resistant starch and soluble fiber that feed beneficial gut bacteria and improve insulin sensitivity.",
                "Outstanding source of folate — one cup provides about 64% of the daily requirement.",
                "Iron, zinc, and magnesium content supports energy, immune function, and muscle recovery.",
            ],
            "it": [
                "Eccezionalmente ricchi di antociani, gli stessi antiossidanti dei mirtilli, che proteggono le cellule.",
                "Alto contenuto di amido resistente e fibre solubili che nutrono i batteri intestinali e migliorano la sensibilità all'insulina.",
                "Fonte eccellente di folati: una tazza copre circa il 64% del fabbisogno giornaliero.",
                "Il ferro, lo zinco e il magnesio supportano energia, immunità e recupero muscolare.",
            ],
            "es": [
                "Excepcionalmente ricos en antocianinas, los mismos antioxidantes de los arándanos, que protegen las células.",
                "Ricos en almidón resistente y fibra soluble que nutren las bacterias intestinales y mejoran la sensibilidad a la insulina.",
                "Fuente excepcional de folato: una taza cubre el 64% de la necesidad diaria.",
                "El hierro, el zinc y el magnesio apoyan la energía, la inmunidad y la recuperación muscular.",
            ],
            "fr": [
                "Exceptionnellement riches en anthocyanes, les mêmes antioxydants que les myrtilles, qui protègent les cellules.",
                "Riches en amidon résistant et en fibres solubles qui nourrissent les bonnes bactéries intestinales et améliorent la sensibilité à l'insuline.",
                "Source remarquable de folate : une tasse couvre environ 64 % des besoins journaliers.",
                "Le fer, le zinc et le magnésium soutiennent l'énergie, l'immunité et la récupération musculaire.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "black beans dinner"},
            "salad": {"source_id": "eatingwell", "query": "black bean salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "black bean breakfast recipes"},
        },
    },
    {
        "id": "pistachios",
        "emoji": "🥜",
        "name": {"ru": "Фисташки", "en": "Pistachios", "it": "Pistacchi", "es": "Pistachos", "fr": "Pistaches"},
        "benefits": {
            "ru": [
                "Одни из самых богатых белком орехов — около 6 г на 30 г, отлично насыщают и поддерживают мышцы.",
                "Богаты лютеином и зеаксантином — антиоксидантами, защищающими зрение и замедляющими возрастные изменения.",
                "Исследования показывают, что регулярное употребление снижает уровень ЛПНП и улучшает работу сосудов.",
                "Хороший источник B6 и калия для здоровья мозга, нервной системы и нормализации давления.",
            ],
            "en": [
                "Among the highest-protein nuts with about 6 g per ounce, great for satiety and muscle support.",
                "Rich in lutein and zeaxanthin, antioxidants that protect eye health and reduce age-related decline.",
                "Studies show regular consumption reduces LDL cholesterol and improves blood vessel function.",
                "Good source of B6 and potassium supporting brain health, nerve function, and blood pressure.",
            ],
            "it": [
                "Tra i più proteici tra le noci: circa 6 g per 30 g, ottimi per il senso di sazietà e il supporto muscolare.",
                "Ricchi di luteina e zeaxantina, antiossidanti che proteggono la vista e riducono il declino legato all'età.",
                "Studi mostrano che il consumo regolare riduce il colesterolo LDL e migliora la funzione vascolare.",
                "Buona fonte di B6 e potassio per la salute del cervello, la funzione nervosa e la pressione arteriosa.",
            ],
            "es": [
                "Entre los frutos secos más proteicos: unos 6 g por 30 g, excelentes para la saciedad y el apoyo muscular.",
                "Ricos en luteína y zeaxantina, antioxidantes que protegen la vista y reducen el deterioro relacionado con la edad.",
                "Estudios muestran que el consumo regular reduce el colesterol LDL y mejora la función vascular.",
                "Buena fuente de B6 y potasio para la salud cerebral, la función nerviosa y la presión arterial.",
            ],
            "fr": [
                "Parmi les oléagineux les plus protéinés : environ 6 g par 30 g, excellents pour la satiété et le maintien musculaire.",
                "Riches en lutéine et zéaxanthine, des antioxydants qui protègent la vue et ralentissent le déclin lié à l'âge.",
                "Des études montrent que leur consommation régulière réduit le cholestérol LDL et améliore la fonction vasculaire.",
                "Bonne source de B6 et de potassium pour la santé cérébrale, la fonction nerveuse et la pression artérielle.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "pistachio chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "pistachio salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "pistachio breakfast recipes"},
        },
    },
    {
        "id": "cashews",
        "emoji": "🥜",
        "name": {"ru": "Кешью", "en": "Cashews", "it": "Anacardi", "es": "Anacardos", "fr": "Noix de cajou"},
        "benefits": {
            "ru": [
                "Богаты магнием — 20% суточной нормы на 30 г — поддерживающим мышцы и качество сна.",
                "Содержат медь, необходимую для усвоения железа, синтеза коллагена и иммунной защиты.",
                "Мононенасыщенные жиры кешью поддерживают здоровый баланс ЛПНП и ЛПВП холестерина.",
                "Хороший источник цинка для заживления ран, иммунитета и здоровья кожи.",
            ],
            "en": [
                "Rich in magnesium — 20% of the daily value per ounce — supporting muscle function and sleep.",
                "Contain copper essential for iron absorption, collagen synthesis, and immune defense.",
                "Monounsaturated fats in cashews support healthy LDL and HDL cholesterol balance.",
                "Good source of zinc promoting wound healing, immune function, and healthy skin.",
            ],
            "it": [
                "Ricchi di magnesio — il 20% del valore giornaliero per 30 g — a supporto della funzione muscolare e del sonno.",
                "Contengono rame essenziale per l'assorbimento del ferro, la sintesi del collagene e le difese immunitarie.",
                "I grassi monoinsaturi degli anacardi supportano un sano equilibrio tra colesterolo LDL e HDL.",
                "Buona fonte di zinco che favorisce la cicatrizzazione, l'immunità e la salute della pelle.",
            ],
            "es": [
                "Ricos en magnesio — el 20% del valor diario por 30 g — que apoya la función muscular y el sueño.",
                "Contienen cobre esencial para la absorción del hierro, la síntesis de colágeno y las defensas inmunitarias.",
                "Las grasas monoinsaturadas de los anacardos apoyan un equilibrio saludable entre el colesterol LDL y HDL.",
                "Buena fuente de zinc para la cicatrización de heridas, la inmunidad y la salud de la piel.",
            ],
            "fr": [
                "Riches en magnésium — 20 % de la valeur quotidienne par 30 g — soutenant la fonction musculaire et le sommeil.",
                "Contiennent du cuivre essentiel à l'absorption du fer, à la synthèse du collagène et aux défenses immunitaires.",
                "Les graisses monoinsaturées des noix de cajou soutiennent un équilibre sain entre cholestérol LDL et HDL.",
                "Bonne source de zinc favorisant la cicatrisation, l'immunité et la santé de la peau.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "cashew chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "cashew salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "cashew breakfast recipes"},
        },
    },
    {
        "id": "hazelnuts",
        "emoji": "🌰",
        "name": {"ru": "Фундук", "en": "Hazelnuts", "it": "Nocciole", "es": "Avellanas", "fr": "Noisettes"},
        "benefits": {
            "ru": [
                "Рекордное среди орехов содержание витамина E — мощного жирорастворимого антиоксиданта, защищающего клетки.",
                "Богаты олеиновой кислотой — той же полезной для сердца мононенасыщенной жирной кислотой, что и в оливковом масле.",
                "Хороший источник марганца и меди для формирования костей и энергетического обмена.",
                "Содержат проантоцианидины, улучшающие функцию сосудов и снижающие воспаление.",
            ],
            "en": [
                "Highest nut source of vitamin E — a powerful fat-soluble antioxidant protecting cells from oxidative damage.",
                "Rich in oleic acid, the same heart-healthy monounsaturated fat found in olive oil.",
                "Good source of manganese and copper supporting bone formation and energy metabolism.",
                "Contain proanthocyanidins linked to improved blood vessel function and reduced inflammation.",
            ],
            "it": [
                "La fonte di vitamina E più ricca tra le noci — un potente antiossidante liposolubile che protegge le cellule.",
                "Ricche di acido oleico, lo stesso grasso monoinsaturo salutare per il cuore presente nell'olio d'oliva.",
                "Buona fonte di manganese e rame a supporto della formazione ossea e del metabolismo energetico.",
                "Contengono proantocianidine associate a una migliore funzione vascolare e a una ridotta infiammazione.",
            ],
            "es": [
                "La fuente más rica en vitamina E entre los frutos secos — un potente antioxidante liposoluble que protege las células.",
                "Ricas en ácido oleico, la misma grasa monoinsaturada saludable para el corazón que se encuentra en el aceite de oliva.",
                "Buena fuente de manganeso y cobre para la formación ósea y el metabolismo energético.",
                "Contienen proantocianidinas asociadas a una mejor función vascular y menor inflamación.",
            ],
            "fr": [
                "La source de vitamine E la plus riche parmi les oléagineux — un puissant antioxydant liposoluble qui protège les cellules.",
                "Riches en acide oléique, la même graisse monoinsaturée bénéfique pour le cœur que dans l'huile d'olive.",
                "Bonne source de manganèse et de cuivre pour la formation osseuse et le métabolisme énergétique.",
                "Contiennent des proanthocyanidines associées à une meilleure fonction vasculaire et à une inflammation réduite.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "hazelnut crusted fish dinner"},
            "salad": {"source_id": "eatingwell", "query": "hazelnut salad"},
            "breakfast": {"source_id": "eatingwell", "query": "hazelnut breakfast recipes"},
        },
    },
    {
        "id": "pine_nuts",
        "emoji": "🌰",
        "name": {"ru": "Кедровый орех", "en": "Pine nuts", "it": "Pinoli", "es": "Piñones", "fr": "Pignons de pin"},
        "benefits": {
            "ru": [
                "Уникальный источник пинолевой кислоты — жирной кислоты, подавляющей аппетит за счёт стимуляции гормонов сытости.",
                "Богаты мононенасыщенными жирами и витамином E, поддерживающими здоровье сердечно-сосудистой системы.",
                "Хороший источник магния и цинка для выработки энергии и иммунной защиты.",
                "Содержат марганец — 30 г покрывают более 100% суточной нормы — важного для костного обмена.",
            ],
            "en": [
                "Unique source of pinolenic acid, a fatty acid shown to suppress appetite by stimulating satiety hormones.",
                "Rich in monounsaturated fats and vitamin E supporting cardiovascular health.",
                "Good source of magnesium and zinc important for energy production and immune defense.",
                "Contain manganese — one ounce provides over 100% of the daily requirement — vital for bone metabolism.",
            ],
            "it": [
                "Fonte unica di acido pinolenico, un acido grasso che riduce l'appetito stimolando gli ormoni della sazietà.",
                "Ricchi di grassi monoinsaturi e vitamina E a supporto della salute cardiovascolare.",
                "Buona fonte di magnesio e zinco importanti per la produzione di energia e le difese immunitarie.",
                "Contengono manganese: 30 g coprono oltre il 100% del fabbisogno giornaliero, vitale per il metabolismo osseo.",
            ],
            "es": [
                "Fuente única de ácido pinolínico, un ácido graso que suprime el apetito estimulando las hormonas de saciedad.",
                "Ricos en grasas monoinsaturadas y vitamina E para la salud cardiovascular.",
                "Buena fuente de magnesio y zinc para la producción de energía y las defensas inmunitarias.",
                "Contienen manganeso: 30 g cubren más del 100% de la necesidad diaria, vital para el metabolismo óseo.",
            ],
            "fr": [
                "Source unique d'acide pinolénique, un acide gras qui supprime l'appétit en stimulant les hormones de satiété.",
                "Riches en graisses monoinsaturées et en vitamine E pour la santé cardiovasculaire.",
                "Bonne source de magnésium et de zinc pour la production d'énergie et les défenses immunitaires.",
                "Contiennent du manganèse : 30 g couvrent plus de 100 % des besoins journaliers, vital pour le métabolisme osseux.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "pine nut pasta dinner"},
            "salad": {"source_id": "eatingwell", "query": "pine nut salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "pine nut breakfast recipes"},
        },
    },
    {
        "id": "flaxseed",
        "emoji": "🌱",
        "name": {"ru": "Семена льна", "en": "Flaxseed", "it": "Semi di lino", "es": "Semillas de lino", "fr": "Graines de lin"},
        "benefits": {
            "ru": [
                "Богатейший растительный источник жирных кислот омега-3 ALA для здоровья сердца и мозга.",
                "Много лигнанов — растительных эстрогенов с антиоксидантными свойствами, снижающих риск онкологии.",
                "Растворимая клетчатка образует гель в кишечнике, замедляя всасывание глюкозы и снижая холестерин.",
                "Хороший источник магния, тиамина и фосфора для энергетического обмена и здоровья костей.",
            ],
            "en": [
                "Richest plant source of omega-3 ALA fatty acids, supporting heart and brain health.",
                "High in lignans — plant estrogens with antioxidant properties linked to reduced cancer risk.",
                "Soluble fiber forms a gel in the gut, slowing glucose absorption and lowering cholesterol.",
                "Good source of magnesium, thiamine, and phosphorus supporting energy metabolism and bone health.",
            ],
            "it": [
                "La fonte vegetale più ricca di acidi grassi omega-3 ALA, a supporto di cuore e cervello.",
                "Alto contenuto di lignani — estrogeni vegetali antiossidanti associati a un ridotto rischio di cancro.",
                "Le fibre solubili formano un gel nell'intestino, rallentando l'assorbimento del glucosio e abbassando il colesterolo.",
                "Buona fonte di magnesio, tiamina e fosforo a supporto del metabolismo energetico e della salute ossea.",
            ],
            "es": [
                "La fuente vegetal más rica en ácidos grasos omega-3 ALA, para la salud del corazón y el cerebro.",
                "Alto contenido en lignanos, fitoestrógenos antioxidantes asociados con menor riesgo de cáncer.",
                "La fibra soluble forma un gel en el intestino, ralentizando la absorción de glucosa y reduciendo el colesterol.",
                "Buena fuente de magnesio, tiamina y fósforo para el metabolismo energético y la salud ósea.",
            ],
            "fr": [
                "La source végétale la plus riche en acides gras oméga-3 ALA, pour la santé du cœur et du cerveau.",
                "Riche en lignanes — des phytoestrogènes antioxydants associés à un risque réduit de cancer.",
                "Les fibres solubles forment un gel dans l'intestin, ralentissant l'absorption du glucose et abaissant le cholestérol.",
                "Bonne source de magnésium, de thiamine et de phosphore pour le métabolisme énergétique et la santé osseuse.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "flaxseed chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "flaxseed salad dressing"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "flaxseed breakfast porridge"},
        },
    },
    {
        "id": "pumpkin_seeds",
        "emoji": "🎃",
        "name": {"ru": "Семена тыквы", "en": "Pumpkin seeds", "it": "Semi di zucca", "es": "Semillas de calabaza", "fr": "Graines de citrouille"},
        "benefits": {
            "ru": [
                "Один из лучших растительных источников цинка, критически важного для иммунитета и выработки тестостерона.",
                "Исключительно богаты магнием — 30 г покрывают около 37% суточной нормы.",
                "Содержат триптофан, превращающийся в серотонин и мелатонин, — поддерживают настроение и сон.",
                "Хороший растительный источник омега-3 ALA и антиоксидантного витамина E.",
            ],
            "en": [
                "One of the best plant sources of zinc, crucial for immune function and testosterone production.",
                "Exceptionally rich in magnesium — one ounce provides about 37% of the daily requirement.",
                "Contain tryptophan converted to serotonin and melatonin, supporting mood and sleep quality.",
                "Good source of plant-based omega-3 ALA fatty acids and antioxidant vitamin E.",
            ],
            "it": [
                "Una delle migliori fonti vegetali di zinco, fondamentale per l'immunità e la produzione di testosterone.",
                "Eccezionalmente ricchi di magnesio: 30 g coprono circa il 37% del fabbisogno giornaliero.",
                "Contengono triptofano convertito in serotonina e melatonina, favorendo l'umore e la qualità del sonno.",
                "Buona fonte di acidi grassi omega-3 ALA di origine vegetale e vitamina E antiossidante.",
            ],
            "es": [
                "Una de las mejores fuentes vegetales de zinc, esencial para la inmunidad y la producción de testosterona.",
                "Excepcionalmente ricas en magnesio: 30 g cubren el 37% de la necesidad diaria.",
                "Contienen triptófano que se convierte en serotonina y melatonina, apoyando el estado de ánimo y el sueño.",
                "Buena fuente vegetal de ácidos grasos omega-3 ALA y vitamina E antioxidante.",
            ],
            "fr": [
                "L'une des meilleures sources végétales de zinc, crucial pour l'immunité et la production de testostérone.",
                "Exceptionnellement riches en magnésium : 30 g couvrent environ 37 % des besoins journaliers.",
                "Contiennent du tryptophane converti en sérotonine et mélatonine, favorisant l'humeur et la qualité du sommeil.",
                "Bonne source d'acides gras oméga-3 ALA d'origine végétale et de vitamine E antioxydante.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "pumpkin seed roasted vegetables dinner"},
            "salad": {"source_id": "eatingwell", "query": "pumpkin seed salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "pumpkin seed granola breakfast"},
        },
    },
    {
        "id": "sunflower_seeds",
        "emoji": "🌻",
        "name": {"ru": "Семена подсолнечника", "en": "Sunflower seeds", "it": "Semi di girasole", "es": "Semillas de girasol", "fr": "Graines de tournesol"},
        "benefits": {
            "ru": [
                "Выдающийся источник витамина E — 30 г покрывают около 37% суточной нормы.",
                "Богаты селеном — микроэлементом с мощными антиоксидантными свойствами, поддерживающим работу щитовидной железы.",
                "Высокое содержание фитостеринов, которые конкурируют с пищевым холестерином, снижая уровень ЛПНП.",
                "Хороший источник витаминов B1 и B6, важных для энергетического обмена и здоровья мозга.",
            ],
            "en": [
                "Outstanding source of vitamin E — one ounce provides about 37% of the daily requirement.",
                "Rich in selenium, a trace mineral with powerful antioxidant and thyroid-supporting properties.",
                "High in phytosterols that compete with dietary cholesterol for absorption, reducing LDL levels.",
                "Good source of B vitamins especially B1 and B6 supporting energy metabolism and brain health.",
            ],
            "it": [
                "Fonte eccezionale di vitamina E: 30 g coprono circa il 37% del fabbisogno giornaliero.",
                "Ricchi di selenio, un oligoelemento con potenti proprietà antiossidanti e di supporto alla tiroide.",
                "Alto contenuto di fitosteroli che competono con il colesterolo alimentare per l'assorbimento, riducendo i livelli di LDL.",
                "Buona fonte di vitamina B1 e B6 a supporto del metabolismo energetico e della salute cerebrale.",
            ],
            "es": [
                "Fuente excepcional de vitamina E: 30 g cubren el 37% de la necesidad diaria.",
                "Ricos en selenio, un oligoelemento con potentes propiedades antioxidantes y de apoyo a la tiroides.",
                "Alto contenido en fitoesteroles que compiten con el colesterol dietético, reduciendo los niveles de LDL.",
                "Buena fuente de vitaminas B1 y B6 para el metabolismo energético y la salud cerebral.",
            ],
            "fr": [
                "Source exceptionnelle de vitamine E : 30 g couvrent environ 37 % des besoins journaliers.",
                "Riches en sélénium, un oligo-élément aux puissantes propriétés antioxydantes et de soutien thyroïdien.",
                "Haute teneur en phytostérols qui entrent en compétition avec le cholestérol alimentaire, réduisant les niveaux de LDL.",
                "Bonne source de vitamines B1 et B6 pour le métabolisme énergétique et la santé cérébrale.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "sunflower seed crusted fish dinner"},
            "salad": {"source_id": "eatingwell", "query": "sunflower seed salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "sunflower seed granola breakfast"},
        },
    },
    {
        "id": "sesame",
        "emoji": "🌱",
        "name": {"ru": "Кунжут", "en": "Sesame", "it": "Sesamo", "es": "Sésamo", "fr": "Sésame"},
        "benefits": {
            "ru": [
                "Отличный источник кальция — 3 столовые ложки кунжута без шелухи покрывают около 27% суточной нормы.",
                "Богат сезамином и сезамолином — уникальными лигнанами, снижающими холестерин и воспаление.",
                "Хороший растительный источник белка и полезных моно- и полиненасыщенных жиров.",
                "Содержит цинк, железо и витамины группы B, необходимые для иммунитета и выработки энергии.",
            ],
            "en": [
                "Excellent source of calcium — 3 tablespoons of hulled sesame provide about 27% of daily needs.",
                "Rich in sesamin and sesamolin, unique lignans with cholesterol-lowering and anti-inflammatory effects.",
                "Good source of plant protein, healthy monounsaturated and polyunsaturated fats.",
                "Contains zinc, iron, and B vitamins essential for immune function and energy production.",
            ],
            "it": [
                "Ottima fonte di calcio: 3 cucchiai di sesamo decorticato coprono circa il 27% del fabbisogno giornaliero.",
                "Ricco di sesamina e sesamolina, lignani unici che abbassano il colesterolo e hanno effetti antinfiammatori.",
                "Buona fonte di proteine vegetali, grassi monoinsaturi e polinsaturi salutari.",
                "Contiene zinco, ferro e vitamina B essenziali per l'immunità e la produzione di energia.",
            ],
            "es": [
                "Excelente fuente de calcio: 3 cucharadas de sésamo sin cáscara cubren el 27% de la necesidad diaria.",
                "Rico en sesamina y sesamolina, lignanos únicos que reducen el colesterol y tienen efectos antiinflamatorios.",
                "Buena fuente de proteína vegetal y grasas monoinsaturadas y poliinsaturadas saludables.",
                "Contiene zinc, hierro y vitaminas B esenciales para la inmunidad y la producción de energía.",
            ],
            "fr": [
                "Excellente source de calcium : 3 cuillères à soupe de sésame décortiqué couvrent environ 27 % des besoins.",
                "Riche en sésamine et sésamoline, des lignanes uniques qui abaissent le cholestérol et réduisent l'inflammation.",
                "Bonne source de protéines végétales et de graisses monoinsaturées et polyinsaturées saines.",
                "Contient du zinc, du fer et des vitamines B essentiels à l'immunité et à la production d'énergie.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "sesame chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "sesame salad dressing"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "sesame breakfast recipes"},
        },
    },
    {
        "id": "peanuts",
        "emoji": "🥜",
        "name": {"ru": "Арахис", "en": "Peanuts", "it": "Arachidi", "es": "Cacahuetes", "fr": "Cacahuètes"},
        "benefits": {
            "ru": [
                "Выдающийся источник растительного белка — 28 г на 100 г, сопоставимо с многими животными белками.",
                "Богаты ресвератролом — тем же антиоксидантом, что в красном вине, с кардиозащитными свойствами.",
                "Хороший источник ниацина (B3) и фолиевой кислоты для здоровья мозга и восстановления клеток.",
                "Гарвардское исследование Nurses' Health Study связывает регулярное употребление арахиса со снижением риска болезней сердца.",
            ],
            "en": [
                "Outstanding source of plant protein — 28 g per 100 g, comparable to many animal proteins.",
                "Rich in resveratrol, the same antioxidant found in red wine, with heart-protective properties.",
                "Good source of niacin (B3) and folate supporting brain health and cell repair.",
                "Harvard Nurses' Health Study links regular peanut consumption to reduced heart disease risk.",
            ],
            "it": [
                "Fonte eccezionale di proteine vegetali: 28 g per 100 g, paragonabile a molte proteine animali.",
                "Ricchi di resveratrolo, lo stesso antiossidante del vino rosso, con proprietà cardioprotettive.",
                "Buona fonte di niacina (B3) e folati a supporto della salute cerebrale e della riparazione cellulare.",
                "Lo studio Nurses' Health Study di Harvard associa il consumo regolare di arachidi a un ridotto rischio di malattie cardiache.",
            ],
            "es": [
                "Fuente excepcional de proteína vegetal: 28 g por 100 g, comparable a muchas proteínas animales.",
                "Ricos en resveratrol, el mismo antioxidante del vino tinto, con propiedades cardioprotectoras.",
                "Buena fuente de niacina (B3) y folato para la salud cerebral y la reparación celular.",
                "El estudio Nurses' Health Study de Harvard asocia el consumo regular de cacahuetes con menor riesgo de enfermedades cardíacas.",
            ],
            "fr": [
                "Source exceptionnelle de protéines végétales : 28 g pour 100 g, comparable à de nombreuses protéines animales.",
                "Riches en resvératrol, le même antioxydant que dans le vin rouge, aux propriétés cardioprotectrices.",
                "Bonne source de niacine (B3) et de folate pour la santé cérébrale et la réparation cellulaire.",
                "La Nurses' Health Study de Harvard associe la consommation régulière de cacahuètes à un risque réduit de maladies cardiaques.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "peanut chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "peanut salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "peanut butter breakfast"},
        },
    },
    {
        "id": "tofu",
        "emoji": "🧈",
        "name": {"ru": "Тофу", "en": "Tofu", "it": "Tofu", "es": "Tofu", "fr": "Tofu"},
        "benefits": {
            "ru": [
                "Полноценный растительный белок, содержащий все незаменимые аминокислоты — около 20 г на 200 г.",
                "Богат изофлавонами, снижающими ЛПНП холестерин, улучшающими плотность костей и гормональный баланс.",
                "Хороший источник кальция, железа и марганца для здоровья костей и энергетического обмена.",
                "Мало калорий и насыщенных жиров — идеален для сердечно-сосудистого и растительного питания.",
            ],
            "en": [
                "Complete plant protein containing all essential amino acids, with about 20 g per 200 g serving.",
                "Rich in isoflavones linked to reduced LDL cholesterol, improved bone density, and hormone balance.",
                "Good source of calcium, iron, and manganese supporting bone health and energy metabolism.",
                "Naturally low in calories and saturated fat, making it ideal for heart-healthy and plant-based diets.",
            ],
            "it": [
                "Proteina vegetale completa con tutti gli aminoacidi essenziali: circa 20 g per 200 g di porzione.",
                "Ricco di isoflavoni associati a riduzione del colesterolo LDL, miglioramento della densità ossea ed equilibrio ormonale.",
                "Buona fonte di calcio, ferro e manganese a supporto della salute ossea e del metabolismo energetico.",
                "Naturalmente povero di calorie e grassi saturi, ideale per diete salutari per il cuore e a base vegetale.",
            ],
            "es": [
                "Proteína vegetal completa con todos los aminoácidos esenciales: unos 20 g por 200 g de porción.",
                "Rico en isoflavonas asociadas con la reducción del colesterol LDL, mayor densidad ósea y equilibrio hormonal.",
                "Buena fuente de calcio, hierro y manganeso para la salud ósea y el metabolismo energético.",
                "Naturalmente bajo en calorías y grasas saturadas, ideal para dietas saludables para el corazón y a base de plantas.",
            ],
            "fr": [
                "Protéine végétale complète contenant tous les acides aminés essentiels : environ 20 g pour 200 g.",
                "Riche en isoflavones associées à la réduction du cholestérol LDL, à l'amélioration de la densité osseuse et à l'équilibre hormonal.",
                "Bonne source de calcium, de fer et de manganèse pour la santé osseuse et le métabolisme énergétique.",
                "Naturellement pauvre en calories et en graisses saturées, idéal pour les régimes sains pour le cœur et à base de plantes.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "tofu dinner recipes"},
            "salad": {"source_id": "eatingwell", "query": "tofu salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "tofu scramble breakfast"},
        },
    },
    {
        "id": "buckwheat",
        "emoji": "🌾",
        "name": {"ru": "Гречка", "en": "Buckwheat", "it": "Grano saraceno", "es": "Trigo sarraceno", "fr": "Sarrasin"},
        "benefits": {
            "ru": [
                "Не содержит глютена и является полноценным белком со всеми незаменимыми аминокислотами.",
                "Богата рутином — мощным флавоноидом, укрепляющим стенки сосудов и снижающим воспаление.",
                "Высокое содержание резистентного крахмала и клетчатки стабилизирует сахар в крови и питает микрофлору кишечника.",
                "Хороший источник магния, марганца и фосфора для здоровья сердца и костей.",
            ],
            "en": [
                "Naturally gluten-free and a complete protein containing all essential amino acids.",
                "Rich in rutin, a powerful flavonoid that strengthens blood vessel walls and reduces inflammation.",
                "High in resistant starch and fiber that stabilize blood sugar and feed gut microbiota.",
                "Good source of magnesium, manganese, and phosphorus supporting heart and bone health.",
            ],
            "it": [
                "Naturalmente privo di glutine e proteina completa con tutti gli aminoacidi essenziali.",
                "Ricco di rutina, un potente flavonoide che rinforza le pareti dei vasi sanguigni e riduce l'infiammazione.",
                "Alto contenuto di amido resistente e fibre che stabilizzano la glicemia e nutrono la microbiota intestinale.",
                "Buona fonte di magnesio, manganese e fosforo a supporto della salute cardiovascolare e ossea.",
            ],
            "es": [
                "Naturalmente libre de gluten y proteína completa con todos los aminoácidos esenciales.",
                "Rico en rutina, un potente flavonoide que fortalece las paredes vasculares y reduce la inflamación.",
                "Alto contenido en almidón resistente y fibra que estabiliza el azúcar en sangre y nutre la microbiota intestinal.",
                "Buena fuente de magnesio, manganeso y fósforo para la salud cardiovascular y ósea.",
            ],
            "fr": [
                "Naturellement sans gluten et protéine complète contenant tous les acides aminés essentiels.",
                "Riche en rutine, un puissant flavonoïde qui renforce les parois vasculaires et réduit l'inflammation.",
                "Haute teneur en amidon résistant et en fibres qui stabilisent la glycémie et nourrissent le microbiote intestinal.",
                "Bonne source de magnésium, de manganèse et de phosphore pour la santé cardiovasculaire et osseuse.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "buckwheat dinner bowl"},
            "salad": {"source_id": "eatingwell", "query": "buckwheat salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "buckwheat porridge breakfast"},
        },
    },
    {
        "id": "brown_rice",
        "emoji": "🍚",
        "name": {"ru": "Бурый рис", "en": "Brown rice", "it": "Riso integrale", "es": "Arroz integral", "fr": "Riz brun"},
        "benefits": {
            "ru": [
                "Цельное зерно с сохранёнными отрубями и зародышем: значительно больше клетчатки, витаминов и минералов, чем в белом рисе.",
                "Содержит резистентный крахмал и клетчатку, поддерживающие регуляцию сахара в крови и здоровье кишечника.",
                "Богат магнием и селеном для здоровья сердца, иммунитета и работы щитовидной железы.",
                "Гарвардские исследования связывают употребление цельных злаков, включая бурый рис, со снижением риска диабета 2 типа.",
            ],
            "en": [
                "Whole grain with intact bran and germ, providing far more fiber, vitamins, and minerals than white rice.",
                "Contains resistant starch and fiber supporting blood sugar regulation and gut health.",
                "Rich in magnesium and selenium supporting heart health, immunity, and thyroid function.",
                "Harvard research links whole grain consumption including brown rice to reduced type 2 diabetes risk.",
            ],
            "it": [
                "Grano intero con crusca e germe intatti: molto più fibre, vitamine e minerali rispetto al riso bianco.",
                "Contiene amido resistente e fibre a supporto della regolazione della glicemia e della salute intestinale.",
                "Ricco di magnesio e selenio per la salute cardiovascolare, l'immunità e la funzione tiroidea.",
                "La ricerca di Harvard associa il consumo di cereali integrali, incluso il riso integrale, a un ridotto rischio di diabete di tipo 2.",
            ],
            "es": [
                "Grano integral con salvado y germen intactos: mucho más fibra, vitaminas y minerales que el arroz blanco.",
                "Contiene almidón resistente y fibra para la regulación del azúcar en sangre y la salud intestinal.",
                "Rico en magnesio y selenio para la salud cardiovascular, la inmunidad y la función tiroidea.",
                "La investigación de Harvard asocia el consumo de cereales integrales, incluido el arroz integral, con menor riesgo de diabetes tipo 2.",
            ],
            "fr": [
                "Grain entier avec son et germe intacts : bien plus de fibres, vitamines et minéraux que le riz blanc.",
                "Contient de l'amidon résistant et des fibres soutenant la régulation de la glycémie et la santé intestinale.",
                "Riche en magnésium et en sélénium pour la santé cardiovasculaire, l'immunité et la fonction thyroïdienne.",
                "Des recherches de Harvard associent la consommation de céréales complètes dont le riz brun à un risque réduit de diabète de type 2.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "brown rice dinner bowl"},
            "salad": {"source_id": "eatingwell", "query": "brown rice salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "brown rice breakfast porridge"},
        },
    },
    {
        "id": "bulgur",
        "emoji": "🌾",
        "name": {"ru": "Булгур", "en": "Bulgur", "it": "Bulgur", "es": "Bulgur", "fr": "Boulgour"},
        "benefits": {
            "ru": [
                "Один из рекордсменов по клетчатке среди злаков — около 8 г на стакан варёного булгура.",
                "Углевод с низким гликемическим индексом, медленно высвобождающий энергию и стабилизирующий сахар в крови.",
                "Хороший источник марганца, магния и железа для выработки энергии и иммунной функции.",
                "Как цельное зерно, регулярное употребление связывают со снижением риска болезней сердца и диабета 2 типа.",
            ],
            "en": [
                "One of the highest-fiber grains with about 8 g per cooked cup, supporting digestive health.",
                "Low glycemic index carbohydrate that releases energy slowly, benefiting blood sugar control.",
                "Good source of manganese, magnesium, and iron essential for energy and immune function.",
                "As a whole grain, regular consumption is linked to reduced risk of heart disease and type 2 diabetes.",
            ],
            "it": [
                "Tra i cereali più ricchi di fibre: circa 8 g per tazza cotta, a supporto della salute digestiva.",
                "Carboidrato a basso indice glicemico che rilascia energia lentamente, favorendo il controllo della glicemia.",
                "Buona fonte di manganese, magnesio e ferro essenziali per l'energia e la funzione immunitaria.",
                "Come cereale integrale, il consumo regolare è associato a un ridotto rischio di malattie cardiache e diabete di tipo 2.",
            ],
            "es": [
                "Uno de los cereales más ricos en fibra: unos 8 g por taza cocida, para la salud digestiva.",
                "Carbohidrato de bajo índice glucémico que libera energía lentamente, beneficiando el control glucémico.",
                "Buena fuente de manganeso, magnesio y hierro para la energía y la función inmunitaria.",
                "Como cereal integral, el consumo regular se asocia con menor riesgo de enfermedades cardíacas y diabetes tipo 2.",
            ],
            "fr": [
                "L'un des grains les plus riches en fibres : environ 8 g par tasse cuite, pour la santé digestive.",
                "Glucide à faible indice glycémique qui libère l'énergie lentement, bénéfique pour la glycémie.",
                "Bonne source de manganèse, de magnésium et de fer essentiels à l'énergie et à la fonction immunitaire.",
                "En tant que céréale complète, sa consommation régulière est associée à un risque réduit de maladies cardiaques et de diabète de type 2.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "bulgur dinner bowl"},
            "salad": {"source_id": "eatingwell", "query": "tabbouleh bulgur salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "bulgur breakfast porridge"},
        },
    },
    {
        "id": "barley",
        "emoji": "🌾",
        "name": {"ru": "Перловка", "en": "Barley", "it": "Orzo", "es": "Cebada", "fr": "Orge"},
        "benefits": {
            "ru": [
                "Богатейший злак по содержанию бета-глюкановой клетчатки, клинически доказавшей снижение ЛПНП холестерина.",
                "Бета-глюкан также замедляет всасывание глюкозы — перловка один из лучших злаков для контроля сахара.",
                "Богата селеном, марганцем и витаминами группы B для обмена веществ и работы щитовидной железы.",
                "Пребиотическая клетчатка питает полезную микрофлору, поддерживая иммунитет и регулярность пищеварения.",
            ],
            "en": [
                "Richest grain source of beta-glucan fiber, clinically proven to lower LDL cholesterol.",
                "Beta-glucan also slows glucose absorption, making barley one of the best grains for blood sugar management.",
                "High in selenium, manganese, and B vitamins supporting metabolism and thyroid function.",
                "Prebiotic fiber feeds beneficial gut bacteria, supporting immune health and digestive regularity.",
            ],
            "it": [
                "Il cereale più ricco di fibre beta-glucano, clinicamente provate per abbassare il colesterolo LDL.",
                "Il beta-glucano rallenta anche l'assorbimento del glucosio, rendendo l'orzo uno dei migliori cereali per la glicemia.",
                "Ricco di selenio, manganese e vitamine B a supporto del metabolismo e della funzione tiroidea.",
                "Le fibre prebiotiche nutrono i batteri intestinali benefici, supportando l'immunità e la regolarità digestiva.",
            ],
            "es": [
                "El cereal más rico en fibra beta-glucano, clínicamente comprobada para reducir el colesterol LDL.",
                "El beta-glucano también ralentiza la absorción de glucosa, haciendo de la cebada uno de los mejores cereales para la glucemia.",
                "Rica en selenio, manganeso y vitaminas B para el metabolismo y la función tiroidea.",
                "La fibra prebiótica nutre las bacterias intestinales beneficiosas, apoyando la inmunidad y la digestión regular.",
            ],
            "fr": [
                "La céréale la plus riche en fibres bêta-glucane, cliniquement prouvées pour abaisser le cholestérol LDL.",
                "Le bêta-glucane ralentit également l'absorption du glucose, faisant de l'orge l'une des meilleures céréales pour la glycémie.",
                "Riche en sélénium, manganèse et vitamines B pour le métabolisme et la fonction thyroïdienne.",
                "Les fibres prébiotiques nourrissent les bonnes bactéries intestinales, soutenant l'immunité et la régularité digestive.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "barley soup dinner"},
            "salad": {"source_id": "eatingwell", "query": "barley salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "barley porridge breakfast"},
        },
    },
    {
        "id": "whole_grain_bread",
        "emoji": "🍞",
        "name": {"ru": "Цельнозерновой хлеб", "en": "Whole grain bread", "it": "Pane integrale", "es": "Pan integral", "fr": "Pain complet"},
        "benefits": {
            "ru": [
                "Содержит значительно больше клетчатки, витаминов и минералов, чем очищенный белый хлеб.",
                "Регулярное употребление связывают со снижением риска болезней сердца, инсульта и диабета 2 типа.",
                "Витамины группы B — тиамин и ниацин — поддерживают энергетический обмен и здоровье нервной системы.",
                "Ферментация в цельнозерновом хлебе на закваске снижает содержание фитиновой кислоты, улучшая усвоение минералов.",
            ],
            "en": [
                "Provides significantly more fiber, vitamins, and minerals than refined white bread.",
                "Regular consumption is linked to reduced risk of heart disease, stroke, and type 2 diabetes.",
                "B vitamins including thiamine and niacin support energy metabolism and nervous system health.",
                "Fermentation in sourdough whole grain bread reduces phytic acid, improving mineral absorption.",
            ],
            "it": [
                "Fornisce significativamente più fibre, vitamine e minerali rispetto al pane bianco raffinato.",
                "Il consumo regolare è associato a un ridotto rischio di malattie cardiache, ictus e diabete di tipo 2.",
                "Le vitamine B, tra cui tiamina e niacina, supportano il metabolismo energetico e la salute nervosa.",
                "La fermentazione nel pane integrale a lievitazione naturale riduce l'acido fitico, migliorando l'assorbimento dei minerali.",
            ],
            "es": [
                "Aporta significativamente más fibra, vitaminas y minerales que el pan blanco refinado.",
                "El consumo regular se asocia con menor riesgo de enfermedades cardíacas, accidente cerebrovascular y diabetes tipo 2.",
                "Las vitaminas B, como tiamina y niacina, apoyan el metabolismo energético y la salud nerviosa.",
                "La fermentación en el pan integral de masa madre reduce el ácido fítico, mejorando la absorción de minerales.",
            ],
            "fr": [
                "Apporte nettement plus de fibres, de vitamines et de minéraux que le pain blanc raffiné.",
                "Sa consommation régulière est associée à un risque réduit de maladies cardiaques, d'AVC et de diabète de type 2.",
                "Les vitamines B dont la thiamine et la niacine soutiennent le métabolisme énergétique et la santé nerveuse.",
                "La fermentation dans le pain complet au levain réduit l'acide phytique, améliorant l'absorption des minéraux.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "whole grain bread sandwich dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "whole grain bread panzanella salad"},
            "breakfast": {"source_id": "eatingwell", "query": "whole grain toast breakfast"},
        },
    },
    {
        "id": "amaranth",
        "emoji": "🌾",
        "name": {"ru": "Амарант", "en": "Amaranth", "it": "Amaranto", "es": "Amaranto", "fr": "Amarante"},
        "benefits": {
            "ru": [
                "Полноценный растительный белок со всеми незаменимыми аминокислотами, включая лизин, которого нет во многих злаках.",
                "Без глютена и один из самых белковых псевдозлаков — около 9 г на стакан варёного.",
                "Богат железом, кальцием и магнием — исключительно высокое содержание минералов для злака.",
                "Содержит сквален — мощный антиоксидант, присутствующий также в оливковом масле, поддерживающий баланс холестерина.",
            ],
            "en": [
                "Complete plant protein with all essential amino acids, including lysine often absent in other grains.",
                "Naturally gluten-free and one of the most protein-dense pseudograins at about 9 g per cooked cup.",
                "Rich in iron, calcium, and magnesium — exceptionally high mineral content for a grain.",
                "Contains squalene, a potent antioxidant also found in olive oil, supporting cholesterol balance.",
            ],
            "it": [
                "Proteina vegetale completa con tutti gli aminoacidi essenziali, inclusa la lisina spesso assente negli altri cereali.",
                "Naturalmente privo di glutine, tra gli pseudocereali più proteici: circa 9 g per tazza cotta.",
                "Ricco di ferro, calcio e magnesio — contenuto minerale eccezionalmente elevato per un cereale.",
                "Contiene squalene, un potente antiossidante presente anche nell'olio d'oliva, che supporta l'equilibrio del colesterolo.",
            ],
            "es": [
                "Proteína vegetal completa con todos los aminoácidos esenciales, incluida la lisina, ausente en muchos cereales.",
                "Sin gluten y uno de los pseudocereales más proteicos: unos 9 g por taza cocida.",
                "Rico en hierro, calcio y magnesio: contenido mineral excepcionalmente alto para un cereal.",
                "Contiene escualeno, un potente antioxidante también presente en el aceite de oliva, que apoya el equilibrio del colesterol.",
            ],
            "fr": [
                "Protéine végétale complète avec tous les acides aminés essentiels, y compris la lysine souvent absente des autres céréales.",
                "Naturellement sans gluten et l'un des pseudo-céréales les plus protéinées : environ 9 g par tasse cuite.",
                "Riche en fer, calcium et magnésium — teneur en minéraux exceptionnellement élevée pour une céréale.",
                "Contient du squalène, un puissant antioxydant également présent dans l'huile d'olive, qui soutient l'équilibre du cholestérol.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "amaranth grain bowl dinner"},
            "salad": {"source_id": "eatingwell", "query": "amaranth salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "amaranth breakfast porridge"},
        },
    },
    {
        "id": "millet",
        "emoji": "🌾",
        "name": {"ru": "Пшено", "en": "Millet", "it": "Miglio", "es": "Mijo", "fr": "Millet"},
        "benefits": {
            "ru": [
                "Не содержит глютена и легко усваивается — идеально для чувствительного пищеварения.",
                "Хороший источник магния, поддерживающего здоровье сердца и помогающего нормализовать давление.",
                "Богат антиоксидантами, включая феруловую кислоту и катехины, снижающие окислительный стресс.",
                "Содержит растительный белок, витамины группы B и фосфор для здоровья костей и энергетического обмена.",
            ],
            "en": [
                "Naturally gluten-free and easily digestible, making it ideal for sensitive digestive systems.",
                "Good source of magnesium supporting heart health and helping to manage blood pressure.",
                "Rich in antioxidants including ferulic acid and catechins that reduce oxidative stress.",
                "Provides plant protein, B vitamins, and phosphorus supporting bone health and energy metabolism.",
            ],
            "it": [
                "Naturalmente privo di glutine e facilmente digeribile, ideale per i sistemi digestivi sensibili.",
                "Buona fonte di magnesio a supporto della salute cardiaca e della gestione della pressione arteriosa.",
                "Ricco di antiossidanti come l'acido ferulico e le catechine che riducono lo stress ossidativo.",
                "Fornisce proteine vegetali, vitamine B e fosforo a supporto della salute ossea e del metabolismo energetico.",
            ],
            "es": [
                "Naturalmente libre de gluten y de fácil digestión, ideal para digestiones sensibles.",
                "Buena fuente de magnesio para la salud cardiovascular y el control de la presión arterial.",
                "Rico en antioxidantes como el ácido ferúlico y las catequinas que reducen el estrés oxidativo.",
                "Aporta proteína vegetal, vitaminas B y fósforo para la salud ósea y el metabolismo energético.",
            ],
            "fr": [
                "Naturellement sans gluten et facile à digérer, idéal pour les systèmes digestifs sensibles.",
                "Bonne source de magnésium pour la santé cardiaque et la gestion de la pression artérielle.",
                "Riche en antioxydants dont l'acide férulique et les catéchines qui réduisent le stress oxydatif.",
                "Apporte des protéines végétales, des vitamines B et du phosphore pour la santé osseuse et le métabolisme énergétique.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "millet grain bowl dinner"},
            "salad": {"source_id": "eatingwell", "query": "millet salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "millet porridge breakfast"},
        },
    },
    {
        "id": "couscous",
        "emoji": "🍚",
        "name": {"ru": "Кускус", "en": "Couscous", "it": "Cuscus", "es": "Cuscús", "fr": "Couscous"},
        "benefits": {
            "ru": [
                "Цельнозерновой кускус быстрого приготовления содержит хорошее количество клетчатки для пищеварения.",
                "Хороший источник селена — 60% суточной нормы на стакан варёного — мощного антиоксидантного минерала.",
                "Содержит растительный белок и витамины группы B — ниацин и тиамин — для энергетического обмена.",
                "Мало жиров, легко усваивается — лёгкая и универсальная основа для сбалансированных блюд.",
            ],
            "en": [
                "Quick-cooking whole wheat variety provides good amounts of fiber supporting digestive health.",
                "Good source of selenium — 60% of the daily value per cooked cup — a powerful antioxidant mineral.",
                "Provides plant protein and B vitamins including niacin and thiamine for energy metabolism.",
                "Low in fat and easily digestible, making it a light and versatile base for balanced meals.",
            ],
            "it": [
                "La varietà integrale a cottura rapida fornisce buone quantità di fibre a supporto della salute digestiva.",
                "Buona fonte di selenio: il 60% del valore giornaliero per tazza cotta, un potente minerale antiossidante.",
                "Fornisce proteine vegetali e vitamine B incluse niacina e tiamina per il metabolismo energetico.",
                "Povero di grassi e facilmente digeribile: base leggera e versatile per pasti equilibrati.",
            ],
            "es": [
                "La variedad integral de cocción rápida aporta buenas cantidades de fibra para la salud digestiva.",
                "Buena fuente de selenio: el 60% del valor diario por taza cocida, un poderoso mineral antioxidante.",
                "Aporta proteína vegetal y vitaminas B como niacina y tiamina para el metabolismo energético.",
                "Bajo en grasas y fácil de digerir: base ligera y versátil para comidas equilibradas.",
            ],
            "fr": [
                "La variété de blé entier à cuisson rapide apporte de bonnes quantités de fibres pour la santé digestive.",
                "Bonne source de sélénium : 60 % de la valeur quotidienne par tasse cuite, un puissant minéral antioxydant.",
                "Apporte des protéines végétales et des vitamines B dont la niacine et la thiamine pour le métabolisme énergétique.",
                "Pauvre en graisses et facilement digestible : base légère et polyvalente pour des repas équilibrés.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "couscous dinner bowl"},
            "salad": {"source_id": "eatingwell", "query": "couscous salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "couscous breakfast recipes"},
        },
    },
    {
        "id": "sardines",
        "emoji": "🐟",
        "name": {"ru": "Сардины", "en": "Sardines", "it": "Sardine", "es": "Sardinas", "fr": "Sardines"},
        "benefits": {
            "ru": [
                "Исключительно богаты жирными кислотами омега-3 EPA и DHA для здоровья сердца и мозга.",
                "Выдающийся источник витамина B12 — одна банка покрывает более 300% суточной нормы.",
                "Высокое содержание кальция из съедобных костей поддерживает плотность костей и предотвращает остеопороз.",
                "Богаты селеном и витамином D — двумя питательными веществами, дефицит которых распространён в современном питании.",
            ],
            "en": [
                "Exceptionally rich in omega-3 fatty acids EPA and DHA supporting heart and brain health.",
                "Outstanding source of vitamin B12 — one can provides over 300% of the daily requirement.",
                "High calcium content from edible bones supports bone density and prevents osteoporosis.",
                "Rich in selenium and vitamin D, two nutrients commonly deficient in modern diets.",
            ],
            "it": [
                "Eccezionalmente ricche di acidi grassi omega-3 EPA e DHA per la salute cardiovascolare e cerebrale.",
                "Fonte straordinaria di vitamina B12: una lattina copre oltre il 300% del fabbisogno giornaliero.",
                "L'alto contenuto di calcio nelle lische edibili supporta la densità ossea e previene l'osteoporosi.",
                "Ricche di selenio e vitamina D, due nutrienti spesso carenti nell'alimentazione moderna.",
            ],
            "es": [
                "Excepcionalmente ricas en ácidos grasos omega-3 EPA y DHA para la salud cardiovascular y cerebral.",
                "Fuente excepcional de vitamina B12: una lata cubre más del 300% de la necesidad diaria.",
                "El alto contenido de calcio de las espinas comestibles apoya la densidad ósea y previene la osteoporosis.",
                "Ricas en selenio y vitamina D, dos nutrientes frecuentemente deficitarios en la dieta moderna.",
            ],
            "fr": [
                "Exceptionnellement riches en acides gras oméga-3 EPA et DHA pour la santé cardiovasculaire et cérébrale.",
                "Source remarquable de vitamine B12 : une boîte couvre plus de 300 % des besoins journaliers.",
                "La haute teneur en calcium des arêtes comestibles soutient la densité osseuse et prévient l'ostéoporose.",
                "Riches en sélénium et en vitamine D, deux nutriments souvent déficients dans l'alimentation moderne.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "sardine dinner recipes"},
            "salad": {"source_id": "eatingwell", "query": "sardine salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "sardine toast breakfast"},
        },
    },
    {
        "id": "mackerel",
        "emoji": "🐟",
        "name": {"ru": "Скумбрия", "en": "Mackerel", "it": "Sgombro", "es": "Caballa", "fr": "Maquereau"},
        "benefits": {
            "ru": [
                "Один из рекордсменов по содержанию омега-3 EPA и DHA среди рыб, значительно превышающий многие виды.",
                "Очень высокое содержание витамина B12 — 100 г покрывают около 280% суточной нормы.",
                "Отличный источник витамина D и селена для иммунитета и работы щитовидной железы.",
                "Высококачественный белок со всеми незаменимыми аминокислотами для поддержания и восстановления мышц.",
            ],
            "en": [
                "One of the richest fish sources of omega-3 EPA and DHA, far exceeding many other species.",
                "Extremely high in vitamin B12 — 100 g provides around 280% of the daily value.",
                "Excellent source of vitamin D and selenium supporting immunity and thyroid function.",
                "High-quality protein with all essential amino acids supporting muscle maintenance and repair.",
            ],
            "it": [
                "Tra le fonti ittiche più ricche di omega-3 EPA e DHA, molto superiore a molte altre specie.",
                "Altissimo contenuto di vitamina B12: 100 g coprono circa il 280% del valore giornaliero.",
                "Ottima fonte di vitamina D e selenio a supporto dell'immunità e della funzione tiroidea.",
                "Proteina di alta qualità con tutti gli aminoacidi essenziali per il mantenimento e la riparazione muscolare.",
            ],
            "es": [
                "Una de las fuentes más ricas en omega-3 EPA y DHA entre los pescados, superando a muchas otras especies.",
                "Altísimo contenido de vitamina B12: 100 g cubren el 280% del valor diario.",
                "Excelente fuente de vitamina D y selenio para la inmunidad y la función tiroidea.",
                "Proteína de alta calidad con todos los aminoácidos esenciales para el mantenimiento y la recuperación muscular.",
            ],
            "fr": [
                "L'une des sources de poisson les plus riches en oméga-3 EPA et DHA, bien au-delà de nombreuses autres espèces.",
                "Teneur très élevée en vitamine B12 : 100 g couvrent environ 280 % de la valeur quotidienne.",
                "Excellente source de vitamine D et de sélénium pour l'immunité et la fonction thyroïdienne.",
                "Protéine de haute qualité avec tous les acides aminés essentiels pour le maintien et la réparation musculaire.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "mackerel dinner recipes"},
            "salad": {"source_id": "eatingwell", "query": "mackerel salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "smoked mackerel breakfast"},
        },
    },
    {
        "id": "shrimp",
        "emoji": "🦐",
        "name": {"ru": "Креветки", "en": "Shrimp", "it": "Gamberetti", "es": "Gambas", "fr": "Crevettes"},
        "benefits": {
            "ru": [
                "Очень много белка — около 24 г на 100 г — при минимуме калорий и практически без жиров.",
                "Богаты йодом, необходимым для выработки гормонов щитовидной железы и регуляции обмена веществ.",
                "Содержат астаксантин — мощный каротиноидный антиоксидант с противовоспалительными свойствами.",
                "Хороший источник селена, фосфора и B12 для энергетического обмена и иммунной функции.",
            ],
            "en": [
                "Very high in protein — about 24 g per 100 g — with remarkably low calories and virtually no fat.",
                "Rich in iodine essential for thyroid hormone production and metabolic regulation.",
                "Contains astaxanthin, a potent carotenoid antioxidant with anti-inflammatory properties.",
                "Good source of selenium, phosphorus, and B12 supporting energy metabolism and immune function.",
            ],
            "it": [
                "Altissimo contenuto proteico: circa 24 g per 100 g, con pochissime calorie e quasi nessun grasso.",
                "Ricchi di iodio, essenziale per la produzione di ormoni tiroidei e la regolazione metabolica.",
                "Contengono astaxantina, un potente antiossidante carotenoide con proprietà antinfiammatorie.",
                "Buona fonte di selenio, fosforo e B12 a supporto del metabolismo energetico e dell'immunità.",
            ],
            "es": [
                "Altísimo contenido proteico: unos 24 g por 100 g, con muy pocas calorías y prácticamente sin grasa.",
                "Ricas en yodo, esencial para la producción de hormonas tiroideas y la regulación metabólica.",
                "Contienen astaxantina, un potente antioxidante carotenoide con propiedades antiinflamatorias.",
                "Buena fuente de selenio, fósforo y B12 para el metabolismo energético y la función inmunitaria.",
            ],
            "fr": [
                "Très riche en protéines : environ 24 g pour 100 g, avec très peu de calories et presque pas de matières grasses.",
                "Riche en iode, essentiel à la production des hormones thyroïdiennes et à la régulation métabolique.",
                "Contient de l'astaxanthine, un puissant antioxydant caroténoïde aux propriétés anti-inflammatoires.",
                "Bonne source de sélénium, de phosphore et de B12 pour le métabolisme énergétique et l'immunité.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "shrimp dinner recipes"},
            "salad": {"source_id": "eatingwell", "query": "shrimp salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "shrimp scrambled eggs breakfast"},
        },
    },
    {
        "id": "chicken_breast",
        "emoji": "🍗",
        "name": {"ru": "Куриная грудка", "en": "Chicken breast", "it": "Petto di pollo", "es": "Pechuga de pollo", "fr": "Blanc de poulet"},
        "benefits": {
            "ru": [
                "Один из самых постных животных белков — 100 г дают около 31 г белка при минимуме жиров.",
                "Богата витаминами группы B, особенно ниацином и B6, необходимыми для здоровья мозга и энергетического обмена.",
                "Содержит селен и фосфор для работы щитовидной железы и здоровья костей.",
                "Триптофан поддерживает выработку серотонина, положительно влияя на настроение и качество сна.",
            ],
            "en": [
                "One of the leanest animal proteins — 100 g provides about 31 g of protein with minimal fat.",
                "Rich in B vitamins especially niacin and B6 essential for brain health and energy metabolism.",
                "Provides selenium and phosphorus supporting thyroid function and bone health.",
                "Tryptophan content supports serotonin production, positively influencing mood and sleep.",
            ],
            "it": [
                "Una delle proteine animali più magre: 100 g forniscono circa 31 g di proteine con pochissimi grassi.",
                "Ricco di vitamine B, soprattutto niacina e B6, essenziali per la salute cerebrale e il metabolismo energetico.",
                "Fornisce selenio e fosforo a supporto della funzione tiroidea e della salute ossea.",
                "Il triptofano supporta la produzione di serotonina, influenzando positivamente umore e sonno.",
            ],
            "es": [
                "Una de las proteínas animales más magras: 100 g aportan unos 31 g de proteína con mínima grasa.",
                "Rica en vitaminas B, especialmente niacina y B6, esenciales para la salud cerebral y el metabolismo energético.",
                "Aporta selenio y fósforo para la función tiroidea y la salud ósea.",
                "El triptófano favorece la producción de serotonina, influyendo positivamente en el estado de ánimo y el sueño.",
            ],
            "fr": [
                "L'une des protéines animales les plus maigres : 100 g apportent environ 31 g de protéines avec très peu de graisses.",
                "Riche en vitamines B, notamment la niacine et la B6, essentielles pour la santé cérébrale et le métabolisme énergétique.",
                "Apporte du sélénium et du phosphore pour la fonction thyroïdienne et la santé osseuse.",
                "Le tryptophane soutient la production de sérotonine, influençant positivement l'humeur et le sommeil.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "chicken breast dinner"},
            "salad": {"source_id": "eatingwell", "query": "chicken breast salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "chicken breast breakfast recipes"},
        },
    },
    {
        "id": "turkey",
        "emoji": "🦃",
        "name": {"ru": "Индейка", "en": "Turkey", "it": "Tacchino", "es": "Pavo", "fr": "Dinde"},
        "benefits": {
            "ru": [
                "Отличный постный белок — 100 г грудки дают около 29 г белка при очень малом содержании жира.",
                "Один из лучших пищевых источников селена для антиоксидантной защиты и здоровья щитовидной железы.",
                "Богата триптофаном — предшественником серотонина и мелатонина, поддерживающим настроение и сон.",
                "Хороший источник цинка и витаминов группы B, включая B6 и B12, для иммунитета и обмена веществ.",
            ],
            "en": [
                "Excellent lean protein source — 100 g of breast provides about 29 g protein with very little fat.",
                "One of the best dietary sources of selenium supporting antioxidant defense and thyroid health.",
                "Rich in tryptophan, a precursor to serotonin and melatonin supporting mood regulation and sleep.",
                "Good source of zinc and B vitamins including B6 and B12 for immune function and metabolism.",
            ],
            "it": [
                "Ottima fonte di proteine magre: 100 g di petto forniscono circa 29 g di proteine con pochissimi grassi.",
                "Una delle migliori fonti alimentari di selenio per le difese antiossidanti e la salute tiroidea.",
                "Ricco di triptofano, precursore di serotonina e melatonina che supporta l'umore e il sonno.",
                "Buona fonte di zinco e vitamine B incluse B6 e B12 per l'immunità e il metabolismo.",
            ],
            "es": [
                "Excelente fuente de proteína magra: 100 g de pechuga aportan unos 29 g de proteína con muy poca grasa.",
                "Una de las mejores fuentes dietéticas de selenio para la defensa antioxidante y la salud tiroidea.",
                "Rico en triptófano, precursor de serotonina y melatonina que favorece el estado de ánimo y el sueño.",
                "Buena fuente de zinc y vitaminas B incluidas B6 y B12 para la inmunidad y el metabolismo.",
            ],
            "fr": [
                "Excellente source de protéines maigres : 100 g de blanc apportent environ 29 g de protéines avec très peu de graisses.",
                "L'une des meilleures sources alimentaires de sélénium pour les défenses antioxydantes et la santé thyroïdienne.",
                "Riche en tryptophane, précurseur de la sérotonine et de la mélatonine favorisant l'humeur et le sommeil.",
                "Bonne source de zinc et de vitamines B dont B6 et B12 pour l'immunité et le métabolisme.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "turkey dinner recipes"},
            "salad": {"source_id": "eatingwell", "query": "turkey salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "turkey breakfast recipes"},
        },
    },
    {
        "id": "lean_beef",
        "emoji": "🥩",
        "name": {"ru": "Говядина постная", "en": "Lean beef", "it": "Manzo magro", "es": "Carne de res magra", "fr": "Bœuf maigre"},
        "benefits": {
            "ru": [
                "Выдающийся источник гемового железа — наиболее легко усваиваемой формы, предотвращающей анемию.",
                "Богата цинком — 100 г покрывают около 40% суточной нормы — необходимым для иммунитета.",
                "Полноценный белок со всеми незаменимыми аминокислотами и высоким содержанием креатина для мышечной силы.",
                "Содержит B12, B6 и селен для здоровья нервной системы и антиоксидантной защиты.",
            ],
            "en": [
                "Outstanding source of heme iron, the form most readily absorbed by the body, preventing anemia.",
                "Rich in zinc — 100 g provides about 40% of the daily requirement — essential for immunity.",
                "Complete protein with all essential amino acids and high in creatine supporting muscle strength.",
                "Provides vitamin B12, B6, and selenium supporting neurological health and antioxidant defense.",
            ],
            "it": [
                "Fonte straordinaria di ferro eme, la forma meglio assorbita dall'organismo, che previene l'anemia.",
                "Ricco di zinco: 100 g coprono circa il 40% del fabbisogno giornaliero, essenziale per l'immunità.",
                "Proteina completa con tutti gli aminoacidi essenziali e alto contenuto di creatina a supporto della forza muscolare.",
                "Fornisce vitamina B12, B6 e selenio per la salute neurologica e le difese antiossidanti.",
            ],
            "es": [
                "Fuente excepcional de hierro hemo, la forma mejor absorbida por el organismo, que previene la anemia.",
                "Rica en zinc: 100 g cubren el 40% de la necesidad diaria, esencial para la inmunidad.",
                "Proteína completa con todos los aminoácidos esenciales y alto contenido en creatina para la fuerza muscular.",
                "Aporta vitamina B12, B6 y selenio para la salud neurológica y la defensa antioxidante.",
            ],
            "fr": [
                "Source exceptionnelle de fer héminique, la forme la mieux absorbée par l'organisme, prévenant l'anémie.",
                "Riche en zinc : 100 g couvrent environ 40 % des besoins journaliers, essentiel pour l'immunité.",
                "Protéine complète avec tous les acides aminés essentiels et riche en créatine pour la force musculaire.",
                "Apporte de la vitamine B12, B6 et du sélénium pour la santé neurologique et les défenses antioxydantes.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "lean beef dinner"},
            "salad": {"source_id": "eatingwell", "query": "beef salad recipes"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "beef hash breakfast"},
        },
    },
    {
        "id": "cottage_cheese",
        "emoji": "🧀",
        "name": {"ru": "Творог", "en": "Cottage cheese", "it": "Ricotta magra", "es": "Requesón", "fr": "Fromage blanc"},
        "benefits": {
            "ru": [
                "Отличный высокобелковый молочный продукт — одна чашка даёт около 25 г белка при относительно небольшом числе калорий.",
                "Богат казеином — медленно перевариваемым белком, обеспечивающим стабильное поступление аминокислот, идеально перед сном.",
                "Хороший источник кальция и фосфора для плотности костей и здоровья зубов.",
                "Содержит витамины группы B, особенно B12 и рибофлавин, для энергетического обмена и эритроцитов.",
            ],
            "en": [
                "Excellent high-protein dairy food — one cup provides about 25 g protein with relatively few calories.",
                "Rich in casein, a slow-digesting protein that provides sustained amino acid release ideal overnight.",
                "Good source of calcium and phosphorus essential for bone density and dental health.",
                "Contains B vitamins especially B12 and riboflavin supporting energy metabolism and red blood cells.",
            ],
            "it": [
                "Ottimo latticino ricco di proteine: una tazza fornisce circa 25 g di proteine con relativamente poche calorie.",
                "Ricco di caseina, una proteina a lenta digestione che rilascia aminoacidi in modo prolungato, ideale prima di dormire.",
                "Buona fonte di calcio e fosforo essenziali per la densità ossea e la salute dentale.",
                "Contiene vitamina B12 e riboflavina per il metabolismo energetico e la formazione dei globuli rossi.",
            ],
            "es": [
                "Excelente lácteo rico en proteínas: una taza aporta unos 25 g de proteína con relativamente pocas calorías.",
                "Rico en caseína, una proteína de digestión lenta que libera aminoácidos de forma sostenida, ideal por la noche.",
                "Buena fuente de calcio y fósforo esenciales para la densidad ósea y la salud dental.",
                "Contiene vitaminas B, especialmente B12 y riboflavina, para el metabolismo energético y los glóbulos rojos.",
            ],
            "fr": [
                "Excellent produit laitier riche en protéines : une tasse apporte environ 25 g de protéines avec relativement peu de calories.",
                "Riche en caséine, une protéine à digestion lente qui libère les acides aminés de façon prolongée, idéale avant le coucher.",
                "Bonne source de calcium et de phosphore essentiels pour la densité osseuse et la santé dentaire.",
                "Contient des vitamines B notamment B12 et riboflavine pour le métabolisme énergétique et les globules rouges.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "cottage cheese dinner recipes"},
            "salad": {"source_id": "eatingwell", "query": "cottage cheese salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "cottage cheese breakfast recipes"},
        },
    },
    {
        "id": "kefir",
        "emoji": "🥛",
        "name": {"ru": "Кефир", "en": "Kefir", "it": "Kefir", "es": "Kéfir", "fr": "Kéfir"},
        "benefits": {
            "ru": [
                "Содержит до 61 штамма живых бактерий и дрожжей — один из самых богатых пробиотических продуктов.",
                "Исследования показывают, что регулярное употребление улучшает переносимость лактозы даже у людей с её непереносимостью.",
                "Кефиран и специфические пробиотики снижают артериальное давление и воспаление.",
                "Хороший источник белка, кальция, B12 и витамина K2 для здоровья костей и сердечно-сосудистой системы.",
            ],
            "en": [
                "Contains up to 61 strains of live bacteria and yeasts, providing one of the most diverse probiotic profiles of any food.",
                "Studies show regular consumption improves lactose digestion, making it tolerable for many lactose-intolerant people.",
                "Compounds kefiran and specific probiotics have been shown to reduce blood pressure and inflammation.",
                "Good source of protein, calcium, B12, and vitamin K2 supporting bone and cardiovascular health.",
            ],
            "it": [
                "Contiene fino a 61 ceppi di batteri vivi e lieviti, uno dei profili probiotici più ricchi tra gli alimenti.",
                "Studi mostrano che il consumo regolare migliora la digestione del lattosio, rendendolo tollerabile anche agli intolleranti.",
                "Il kefiran e specifici probiotici riducono la pressione arteriosa e l'infiammazione.",
                "Buona fonte di proteine, calcio, B12 e vitamina K2 per la salute ossea e cardiovascolare.",
            ],
            "es": [
                "Contiene hasta 61 cepas de bacterias vivas y levaduras, uno de los perfiles probióticos más ricos de cualquier alimento.",
                "Estudios muestran que el consumo regular mejora la digestión de la lactosa, haciéndolo tolerable para muchos intolerantes.",
                "El kefiran y probióticos específicos reducen la presión arterial y la inflamación.",
                "Buena fuente de proteína, calcio, B12 y vitamina K2 para la salud ósea y cardiovascular.",
            ],
            "fr": [
                "Contient jusqu'à 61 souches de bactéries vivantes et de levures, l'un des profils probiotiques les plus riches parmi les aliments.",
                "Des études montrent que sa consommation régulière améliore la digestion du lactose, le rendant tolérable pour beaucoup d'intolérants.",
                "Le kéfiran et des probiotiques spécifiques ont montré une réduction de la pression artérielle et de l'inflammation.",
                "Bonne source de protéines, calcium, B12 et vitamine K2 pour la santé osseuse et cardiovasculaire.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "kefir chicken marinade dinner"},
            "salad": {"source_id": "eatingwell", "query": "kefir dressing salad"},
            "breakfast": {"source_id": "eatingwell", "query": "kefir breakfast smoothie"},
        },
    },
    {
        "id": "hard_cheese",
        "emoji": "🧀",
        "name": {"ru": "Сыр твёрдый", "en": "Hard cheese", "it": "Formaggio stagionato", "es": "Queso curado", "fr": "Fromage à pâte dure"},
        "benefits": {
            "ru": [
                "Исключительный источник кальция — 30 г покрывают около 20–25% суточной нормы для здоровья костей.",
                "Богат витамином K2, направляющим кальций в кости, а не в артерии, снижая кардиоваскулярный риск.",
                "Выдержанный твёрдый сыр практически не содержит лактозы и подходит большинству людей с её непереносимостью.",
                "Хороший источник высококачественного белка, B12, фосфора и цинка для мышц и иммунитета.",
            ],
            "en": [
                "Exceptional calcium source — 30 g provides about 20-25% of the daily requirement for bone health.",
                "Rich in vitamin K2 that directs calcium to bones rather than arteries, reducing cardiovascular risk.",
                "Aged hard cheese contains virtually no lactose, making it suitable for most lactose-intolerant people.",
                "Good source of high-quality protein, B12, phosphorus, and zinc supporting muscle and immune health.",
            ],
            "it": [
                "Fonte eccezionale di calcio: 30 g coprono circa il 20-25% del fabbisogno giornaliero per la salute ossea.",
                "Ricco di vitamina K2 che dirige il calcio verso le ossa anziché le arterie, riducendo il rischio cardiovascolare.",
                "Il formaggio stagionato contiene quasi nessun lattosio, adatto alla maggior parte degli intolleranti.",
                "Buona fonte di proteine di alta qualità, B12, fosforo e zinco per i muscoli e l'immunità.",
            ],
            "es": [
                "Fuente excepcional de calcio: 30 g cubren el 20-25% de la necesidad diaria para la salud ósea.",
                "Rico en vitamina K2 que dirige el calcio hacia los huesos en lugar de las arterias, reduciendo el riesgo cardiovascular.",
                "El queso curado contiene prácticamente nada de lactosa, siendo apto para la mayoría de los intolerantes.",
                "Buena fuente de proteína de alta calidad, B12, fósforo y zinc para músculos e inmunidad.",
            ],
            "fr": [
                "Source exceptionnelle de calcium : 30 g couvrent environ 20-25 % des besoins journaliers pour la santé osseuse.",
                "Riche en vitamine K2 qui dirige le calcium vers les os plutôt que les artères, réduisant le risque cardiovasculaire.",
                "Le fromage affiné contient pratiquement pas de lactose, adapté à la plupart des intolérants.",
                "Bonne source de protéines de haute qualité, de B12, de phosphore et de zinc pour les muscles et l'immunité.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "hard cheese pasta dinner"},
            "salad": {"source_id": "eatingwell", "query": "cheese salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "cheese omelette breakfast"},
        },
    },
    {
        "id": "milk",
        "emoji": "🥛",
        "name": {"ru": "Молоко", "en": "Milk", "it": "Latte", "es": "Leche", "fr": "Lait"},
        "benefits": {
            "ru": [
                "Один из наиболее биодоступных источников кальция и фосфора — основа здоровья костей и зубов.",
                "Высококачественный полноценный белок, содержащий казеин и сыворотку для роста и восстановления мышц.",
                "Обогащённое молоко содержит витамин D, необходимый для усвоения кальция и иммунитета.",
                "Содержит калий, B2 и B12 для работы сердца, выработки энергии и здоровья нервной системы.",
            ],
            "en": [
                "One of the most bioavailable sources of calcium and phosphorus, foundational for bone and dental health.",
                "High-quality complete protein containing casein and whey supporting muscle growth and repair.",
                "Fortified milk provides vitamin D essential for calcium absorption and immune function.",
                "Contains potassium, B2, and B12 supporting heart function, energy production, and nerve health.",
            ],
            "it": [
                "Una delle fonti di calcio e fosforo più biodisponibili, fondamentale per la salute di ossa e denti.",
                "Proteina completa di alta qualità contenente caseina e siero di latte per la crescita e riparazione muscolare.",
                "Il latte arricchito fornisce vitamina D essenziale per l'assorbimento del calcio e l'immunità.",
                "Contiene potassio, B2 e B12 per la funzione cardiaca, la produzione di energia e la salute nervosa.",
            ],
            "es": [
                "Una de las fuentes de calcio y fósforo más biodisponibles, esencial para la salud ósea y dental.",
                "Proteína completa de alta calidad con caseína y suero de leche para el crecimiento y la reparación muscular.",
                "La leche enriquecida aporta vitamina D esencial para la absorción del calcio y la inmunidad.",
                "Contiene potasio, B2 y B12 para la función cardíaca, la producción de energía y la salud nerviosa.",
            ],
            "fr": [
                "L'une des sources de calcium et de phosphore les plus biodisponibles, essentielle pour la santé osseuse et dentaire.",
                "Protéine complète de haute qualité contenant de la caséine et du lactosérum pour la croissance et la réparation musculaire.",
                "Le lait enrichi apporte de la vitamine D essentielle à l'absorption du calcium et à l'immunité.",
                "Contient du potassium, de la B2 et de la B12 pour la fonction cardiaque, la production d'énergie et la santé nerveuse.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "milk based sauce dinner"},
            "salad": {"source_id": "bbcgoodfood", "query": "milk dressing salad"},
            "breakfast": {"source_id": "eatingwell", "query": "milk oatmeal breakfast"},
        },
    },
    {
        "id": "mussels",
        "emoji": "🦪",
        "name": {"ru": "Мидии", "en": "Mussels", "it": "Cozze", "es": "Mejillones", "fr": "Moules"},
        "benefits": {
            "ru": [
                "Исключительный источник витамина B12 — 100 г покрывают более 400% суточной нормы.",
                "Богаты жирными кислотами омега-3 EPA и DHA для здоровья сердца и мозга.",
                "Выдающийся источник цинка, железа и селена для иммунитета и антиоксидантной защиты.",
                "Мидии, выращенные на фермах, являются одним из наиболее экологически устойчивых животных белков.",
            ],
            "en": [
                "Extraordinary source of vitamin B12 — 100 g provides over 400% of the daily requirement.",
                "Rich in omega-3 fatty acids EPA and DHA supporting heart and brain health.",
                "Outstanding source of zinc, iron, and selenium crucial for immunity and antioxidant defense.",
                "Sustainably farmed mussels are among the most environmentally friendly animal proteins available.",
            ],
            "it": [
                "Fonte straordinaria di vitamina B12: 100 g coprono oltre il 400% del fabbisogno giornaliero.",
                "Ricche di acidi grassi omega-3 EPA e DHA per la salute cardiovascolare e cerebrale.",
                "Fonte eccellente di zinco, ferro e selenio essenziali per l'immunità e le difese antiossidanti.",
                "Le cozze allevate sono tra le proteine animali più sostenibili dal punto di vista ambientale.",
            ],
            "es": [
                "Fuente extraordinaria de vitamina B12: 100 g cubren más del 400% de la necesidad diaria.",
                "Ricas en ácidos grasos omega-3 EPA y DHA para la salud cardiovascular y cerebral.",
                "Fuente excepcional de zinc, hierro y selenio esenciales para la inmunidad y la defensa antioxidante.",
                "Los mejillones de cultivo son una de las proteínas animales más sostenibles disponibles.",
            ],
            "fr": [
                "Source extraordinaire de vitamine B12 : 100 g couvrent plus de 400 % des besoins journaliers.",
                "Riches en acides gras oméga-3 EPA et DHA pour la santé cardiovasculaire et cérébrale.",
                "Source exceptionnelle de zinc, de fer et de sélénium essentiels à l'immunité et aux défenses antioxydantes.",
                "Les moules d'élevage sont parmi les protéines animales les plus durables sur le plan environnemental.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "mussels dinner recipes"},
            "salad": {"source_id": "eatingwell", "query": "mussels salad recipes"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "mussels seafood brunch"},
        },
    },
    {
        "id": "trout",
        "emoji": "🐟",
        "name": {"ru": "Форель", "en": "Trout", "it": "Trota", "es": "Trucha", "fr": "Truite"},
        "benefits": {
            "ru": [
                "Богата жирными кислотами омега-3 EPA и DHA, ассоциированными со снижением риска болезней сердца и депрессии.",
                "Отличный источник витамина D — 100 г покрывают около 108% суточной нормы.",
                "Высококачественный нежирный белок со всеми незаменимыми аминокислотами для поддержания мышц.",
                "Хороший источник B12, ниацина и селена для щитовидной железы и антиоксидантной функции.",
            ],
            "en": [
                "Rich in omega-3 fatty acids EPA and DHA linked to reduced risk of heart disease and depression.",
                "Excellent source of vitamin D — 100 g provides about 108% of the daily requirement.",
                "High-quality lean protein with all essential amino acids supporting muscle maintenance.",
                "Good source of B vitamins B12 and niacin, plus selenium for thyroid and antioxidant function.",
            ],
            "it": [
                "Ricca di acidi grassi omega-3 EPA e DHA associati a un ridotto rischio di malattie cardiache e depressione.",
                "Ottima fonte di vitamina D: 100 g coprono circa il 108% del fabbisogno giornaliero.",
                "Proteina magra di alta qualità con tutti gli aminoacidi essenziali a supporto del mantenimento muscolare.",
                "Buona fonte di B12, niacina e selenio per la tiroide e la funzione antiossidante.",
            ],
            "es": [
                "Rica en ácidos grasos omega-3 EPA y DHA asociados con menor riesgo de enfermedades cardíacas y depresión.",
                "Excelente fuente de vitamina D: 100 g cubren el 108% de la necesidad diaria.",
                "Proteína magra de alta calidad con todos los aminoácidos esenciales para el mantenimiento muscular.",
                "Buena fuente de B12, niacina y selenio para la tiroides y la función antioxidante.",
            ],
            "fr": [
                "Riche en acides gras oméga-3 EPA et DHA associés à un risque réduit de maladies cardiaques et de dépression.",
                "Excellente source de vitamine D : 100 g couvrent environ 108 % des besoins journaliers.",
                "Protéine maigre de haute qualité avec tous les acides aminés essentiels pour le maintien musculaire.",
                "Bonne source de B12, de niacine et de sélénium pour la thyroïde et la fonction antioxydante.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "trout dinner recipes"},
            "salad": {"source_id": "eatingwell", "query": "trout salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "smoked trout breakfast"},
        },
    },
    {
        "id": "turmeric",
        "emoji": "🟡",
        "name": {"ru": "Куркума", "en": "Turmeric", "it": "Curcuma", "es": "Cúrcuma", "fr": "Curcuma"},
        "benefits": {
            "ru": [
                "Куркумин — активное соединение куркумы — один из наиболее изученных природных противовоспалительных агентов.",
                "Клинические исследования показывают, что куркумин снижает маркеры системного воспаления.",
                "Антиоксидантные свойства нейтрализуют свободные радикалы и усиливают собственную антиоксидантную защиту организма.",
                "Может поддерживать здоровье мозга, повышая уровень BDNF — гормона, стимулирующего образование нейронов.",
            ],
            "en": [
                "Curcumin, turmeric's active compound, is one of the most studied natural anti-inflammatory agents.",
                "Clinical studies show curcumin supplementation can reduce markers of systemic inflammation.",
                "Antioxidant properties neutralize free radicals and boost the body's own antioxidant enzyme activity.",
                "May support brain health by increasing BDNF, a growth hormone that promotes neuron formation.",
            ],
            "it": [
                "La curcumina, il composto attivo della curcuma, è uno degli agenti antinfiammatori naturali più studiati al mondo.",
                "Studi clinici mostrano che la curcumina riduce i marcatori dell'infiammazione sistemica.",
                "Le proprietà antiossidanti neutralizzano i radicali liberi e potenziano l'attività degli enzimi antiossidanti dell'organismo.",
                "Può supportare la salute cerebrale aumentando il BDNF, un ormone della crescita che promuove la formazione neuronale.",
            ],
            "es": [
                "La curcumina, el compuesto activo de la cúrcuma, es uno de los agentes antiinflamatorios naturales más estudiados.",
                "Estudios clínicos muestran que la curcumina reduce los marcadores de inflamación sistémica.",
                "Las propiedades antioxidantes neutralizan los radicales libres y potencian la actividad enzimática antioxidante del cuerpo.",
                "Puede apoyar la salud cerebral aumentando el BDNF, una hormona de crecimiento que promueve la formación neuronal.",
            ],
            "fr": [
                "La curcumine, le composé actif du curcuma, est l'un des agents anti-inflammatoires naturels les plus étudiés.",
                "Des études cliniques montrent que la curcumine réduit les marqueurs de l'inflammation systémique.",
                "Les propriétés antioxydantes neutralisent les radicaux libres et renforcent l'activité des enzymes antioxydantes de l'organisme.",
                "Peut soutenir la santé cérébrale en augmentant le BDNF, une hormone de croissance qui favorise la formation neuronale.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "turmeric chicken dinner"},
            "salad": {"source_id": "eatingwell", "query": "turmeric salad dressing"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "turmeric golden milk breakfast"},
        },
    },
    {
        "id": "cinnamon",
        "emoji": "🟤",
        "name": {"ru": "Корица", "en": "Cinnamon", "it": "Cannella", "es": "Canela", "fr": "Cannelle"},
        "benefits": {
            "ru": [
                "В нескольких клинических исследованиях снижала уровень глюкозы натощак и улучшала чувствительность к инсулину.",
                "Содержит циннамальдегид — антиоксидантное соединение с выраженными противовоспалительными свойствами.",
                "Может снижать уровень ЛПНП холестерина и триглицеридов, поддерживая здоровье сердечно-сосудистой системы.",
                "Содержит антибактериальные и противогрибковые соединения — традиционный природный консервант.",
            ],
            "en": [
                "Shown in multiple clinical trials to lower fasting blood glucose and improve insulin sensitivity.",
                "Contains cinnamaldehyde, an antioxidant compound with potent anti-inflammatory effects.",
                "May help lower LDL cholesterol and triglycerides supporting overall cardiovascular health.",
                "Contains antibacterial and antifungal compounds making it a traditional natural preservative.",
            ],
            "it": [
                "Diversi studi clinici mostrano che abbassa la glicemia a digiuno e migliora la sensibilità all'insulina.",
                "Contiene cinnamaldeide, un composto antiossidante con potenti effetti antinfiammatori.",
                "Può abbassare il colesterolo LDL e i trigliceridi, supportando la salute cardiovascolare.",
                "Contiene composti antibatterici e antifungini, rendendola un tradizionale conservante naturale.",
            ],
            "es": [
                "Múltiples ensayos clínicos muestran que reduce la glucosa en ayunas y mejora la sensibilidad a la insulina.",
                "Contiene cinamaldehído, un compuesto antioxidante con potentes efectos antiinflamatorios.",
                "Puede reducir el colesterol LDL y los triglicéridos, apoyando la salud cardiovascular.",
                "Contiene compuestos antibacterianos y antifúngicos, convirtiéndola en un conservante natural tradicional.",
            ],
            "fr": [
                "Plusieurs essais cliniques montrent qu'elle abaisse la glycémie à jeun et améliore la sensibilité à l'insuline.",
                "Contient du cinnamaldéhyde, un composé antioxydant aux puissants effets anti-inflammatoires.",
                "Peut abaisser le cholestérol LDL et les triglycérides, soutenant la santé cardiovasculaire.",
                "Contient des composés antibactériens et antifongiques, en faisant un conservateur naturel traditionnel.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "cinnamon spiced lamb dinner"},
            "salad": {"source_id": "eatingwell", "query": "cinnamon apple salad"},
            "breakfast": {"source_id": "eatingwell", "query": "cinnamon oatmeal breakfast"},
        },
    },
    {
        "id": "parsley",
        "emoji": "🌿",
        "name": {"ru": "Петрушка", "en": "Parsley", "it": "Prezzemolo", "es": "Perejil", "fr": "Persil"},
        "benefits": {
            "ru": [
                "Исключительно богата витамином K — всего 10 веточек покрывают более 150% суточной нормы.",
                "Отличный источник витамина C и антиоксидантного флавона апигенина.",
                "Содержит мирицетин — флавоноид, изученный на предмет антидиабетических и онкопротекторных свойств.",
                "Богата фолиевой кислотой, железом и калием для здоровья сердца и образования эритроцитов.",
            ],
            "en": [
                "Extraordinarily rich in vitamin K — just 10 sprigs provide over 150% of the daily requirement.",
                "Excellent source of vitamin C and the antioxidant flavone apigenin.",
                "Contains myricetin, a flavonoid studied for anti-diabetic and cancer-protective properties.",
                "Rich in folate, iron, and potassium supporting cardiovascular health and red blood cell production.",
            ],
            "it": [
                "Straordinariamente ricca di vitamina K: solo 10 rametti coprono oltre il 150% del fabbisogno giornaliero.",
                "Ottima fonte di vitamina C e del flavone antiossidante apigenina.",
                "Contiene miricetina, un flavonoide studiato per proprietà antidiabetiche e anticancro.",
                "Ricca di folati, ferro e potassio per la salute cardiovascolare e la produzione di globuli rossi.",
            ],
            "es": [
                "Extraordinariamente rica en vitamina K: solo 10 ramitas cubren más del 150% de la necesidad diaria.",
                "Excelente fuente de vitamina C y del flavonoide antioxidante apigenina.",
                "Contiene miricetina, un flavonoide estudiado por sus propiedades antidiabéticas y anticancerígenas.",
                "Rica en folato, hierro y potasio para la salud cardiovascular y la producción de glóbulos rojos.",
            ],
            "fr": [
                "Extraordinairement riche en vitamine K : 10 tiges seulement couvrent plus de 150 % des besoins journaliers.",
                "Excellente source de vitamine C et du flavone antioxydant apigénine.",
                "Contient de la myricétine, un flavonoïde étudié pour ses propriétés anti-diabétiques et anticancéreuses.",
                "Riche en folate, fer et potassium pour la santé cardiovasculaire et la production de globules rouges.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "parsley chimichurri steak dinner"},
            "salad": {"source_id": "eatingwell", "query": "parsley tabbouleh salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "parsley eggs breakfast"},
        },
    },
    {
        "id": "basil",
        "emoji": "🌿",
        "name": {"ru": "Базилик", "en": "Basil", "it": "Basilico", "es": "Albahaca", "fr": "Basilic"},
        "benefits": {
            "ru": [
                "Богат эвгенолом — природным фенолом с противовоспалительными свойствами, сопоставимыми с ибупрофеном.",
                "Содержит ориентин и вицинин — мощные флавоноиды, защищающие ДНК от окислительного повреждения.",
                "Источник витамина K и марганца, необходимых для свёртываемости крови и антиоксидантной активности.",
                "Адаптогенные свойства помогают снизить уровень стрессовых гормонов и поддержать функцию надпочечников.",
            ],
            "en": [
                "Rich in eugenol, a natural phenol with potent anti-inflammatory properties similar to ibuprofen.",
                "Contains orientin and vicenin, powerful flavonoids that protect DNA from oxidative damage.",
                "Provides vitamin K and manganese important for blood clotting and antioxidant enzyme activity.",
                "Adaptogenic properties may help reduce stress hormones and support adrenal gland function.",
            ],
            "it": [
                "Ricco di eugenolo, un fenolo naturale con potenti proprietà antinfiammatorie simili all'ibuprofene.",
                "Contiene orientin e vicenin, potenti flavonoidi che proteggono il DNA dai danni ossidativi.",
                "Fornisce vitamina K e manganese importanti per la coagulazione e l'attività degli enzimi antiossidanti.",
                "Le proprietà adattogene possono aiutare a ridurre gli ormoni dello stress e supportare la funzione surrenale.",
            ],
            "es": [
                "Rico en eugenol, un fenol natural con potentes propiedades antiinflamatorias similares al ibuprofeno.",
                "Contiene orientina y vicenina, potentes flavonoides que protegen el ADN del daño oxidativo.",
                "Aporta vitamina K y manganeso importantes para la coagulación y la actividad enzimática antioxidante.",
                "Las propiedades adaptógenas pueden ayudar a reducir las hormonas del estrés y apoyar la función adrenal.",
            ],
            "fr": [
                "Riche en eugénol, un phénol naturel aux puissantes propriétés anti-inflammatoires similaires à l'ibuprofène.",
                "Contient de l'orientine et de la vicenine, de puissants flavonoïdes qui protègent l'ADN des dommages oxydatifs.",
                "Apporte de la vitamine K et du manganèse importants pour la coagulation et l'activité des enzymes antioxydantes.",
                "Les propriétés adaptogènes peuvent aider à réduire les hormones du stress et soutenir la fonction surrénalienne.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "basil pesto pasta dinner"},
            "salad": {"source_id": "eatingwell", "query": "caprese basil salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "basil eggs breakfast"},
        },
    },
    {
        "id": "mint",
        "emoji": "🌿",
        "name": {"ru": "Мята", "en": "Mint", "it": "Menta", "es": "Menta", "fr": "Menthe"},
        "benefits": {
            "ru": [
                "Ментол — ключевое соединение мяты — активирует рецепторы холода, расслабляя мышцы пищеварительного тракта и облегчая симптомы СРК.",
                "Клинические исследования показывают, что масло перечной мяты значительно снижает изжогу, вздутие и тошноту.",
                "Содержит розмариновую кислоту — антиоксидант и противовоспалительное соединение, изученное также для облегчения аллергии.",
                "Содержит витамин A, железо, фолиевую кислоту и марганец при минимальном числе калорий.",
            ],
            "en": [
                "Menthol, mint's key compound, activates cold-sensing receptors that relax digestive tract muscles, easing IBS symptoms.",
                "Clinical studies show peppermint oil significantly reduces indigestion, bloating, and nausea.",
                "Contains rosmarinic acid, an antioxidant and anti-inflammatory compound also studied for allergy relief.",
                "Provides small amounts of vitamin A, iron, folate, and manganese with virtually no calories.",
            ],
            "it": [
                "Il mentolo, il composto chiave della menta, attiva i recettori del freddo rilassando i muscoli del tratto digestivo e alleviando i sintomi dell'IBS.",
                "Studi clinici mostrano che l'olio di menta piperita riduce significativamente bruciori, gonfiore e nausea.",
                "Contiene acido rosmarinico, un antiossidante e antinfiammatorio studiato anche per il sollievo delle allergie.",
                "Fornisce piccole quantità di vitamina A, ferro, folati e manganese con quasi nessuna caloria.",
            ],
            "es": [
                "El mentol, el compuesto clave de la menta, activa los receptores del frío relajando los músculos digestivos y aliviando los síntomas del SII.",
                "Estudios clínicos muestran que el aceite de menta piperita reduce significativamente la acidez, la hinchazón y las náuseas.",
                "Contiene ácido rosmarínico, un antioxidante y antiinflamatorio estudiado también para el alivio de alergias.",
                "Aporta pequeñas cantidades de vitamina A, hierro, folato y manganeso con prácticamente ninguna caloría.",
            ],
            "fr": [
                "Le menthol, composé clé de la menthe, active les récepteurs du froid en relaxant les muscles digestifs, soulageant les symptômes du SII.",
                "Des études cliniques montrent que l'huile de menthe poivrée réduit significativement les brûlures, les ballonnements et les nausées.",
                "Contient de l'acide rosmarinique, un antioxydant et anti-inflammatoire également étudié pour le soulagement des allergies.",
                "Apporte de petites quantités de vitamine A, de fer, de folate et de manganèse avec quasiment aucune calorie.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "mint lamb dinner"},
            "salad": {"source_id": "eatingwell", "query": "mint watermelon salad"},
            "breakfast": {"source_id": "eatingwell", "query": "mint smoothie breakfast"},
        },
    },
    {
        "id": "chili_pepper",
        "emoji": "🌶️",
        "name": {"ru": "Перец чили", "en": "Chili pepper", "it": "Peperoncino", "es": "Chile", "fr": "Piment"},
        "benefits": {
            "ru": [
                "Капсаицин — активное соединение — активирует рецепторы TRPV1, ускоряя обмен веществ и сжигание калорий.",
                "Регулярное употребление чили ассоциируется со снижением сердечно-сосудистой смертности в крупных популяционных исследованиях.",
                "Капсаицин обладает выраженными обезболивающими свойствами и используется клинически в препаратах от боли.",
                "Богат витамином C и антиоксидантными каротиноидами, включая бета-каротин и лютеин.",
            ],
            "en": [
                "Capsaicin, the active compound, activates TRPV1 receptors that boost metabolism and increase calorie burning.",
                "Regular chili consumption is associated with reduced cardiovascular mortality in large population studies.",
                "Capsaicin has strong analgesic properties and is used clinically in pain-relief formulations.",
                "Rich in vitamin C and antioxidant carotenoids including beta-carotene and lutein.",
            ],
            "it": [
                "La capsaicina, il composto attivo, attiva i recettori TRPV1 che accelerano il metabolismo e aumentano il dispendio calorico.",
                "Il consumo regolare di peperoncino è associato a una ridotta mortalità cardiovascolare in grandi studi di popolazione.",
                "La capsaicina ha forti proprietà analgesiche ed è usata clinicamente in formulazioni antidolore.",
                "Ricco di vitamina C e carotenoidi antiossidanti tra cui beta-carotene e luteina.",
            ],
            "es": [
                "La capsaicina, el compuesto activo, activa los receptores TRPV1 que aceleran el metabolismo y aumentan el gasto calórico.",
                "El consumo regular de chile se asocia con menor mortalidad cardiovascular en grandes estudios poblacionales.",
                "La capsaicina tiene potentes propiedades analgésicas y se usa clínicamente en formulaciones para el dolor.",
                "Rico en vitamina C y carotenoides antioxidantes como el betacaroteno y la luteína.",
            ],
            "fr": [
                "La capsaïcine, le composé actif, active les récepteurs TRPV1 qui accélèrent le métabolisme et augmentent la dépense calorique.",
                "La consommation régulière de piment est associée à une mortalité cardiovasculaire réduite dans de grandes études de population.",
                "La capsaïcine a de fortes propriétés analgésiques et est utilisée cliniquement dans des formulations contre la douleur.",
                "Riche en vitamine C et en caroténoïdes antioxydants dont le bêta-carotène et la lutéine.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "chili pepper spicy dinner"},
            "salad": {"source_id": "eatingwell", "query": "chili pepper salad dressing"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "chili eggs breakfast"},
        },
    },
    {
        "id": "hummus",
        "emoji": "🥣",
        "name": {"ru": "Хумус", "en": "Hummus", "it": "Hummus", "es": "Hummus", "fr": "Houmous"},
        "benefits": {
            "ru": [
                "Богат растительным белком и клетчаткой из нута, обеспечивая сытость и стабильный уровень сахара.",
                "Тахини и оливковое масло дают полезные для сердца мононенасыщенные жиры и кальций для костей.",
                "Богат фолиевой кислотой, железом и марганцем для выработки энергии и иммунного здоровья.",
                "Исследования связывают регулярное употребление с улучшением разнообразия микробиома и снижением маркеров воспаления.",
            ],
            "en": [
                "High in plant protein and fiber from chickpeas, supporting satiety and stable blood sugar.",
                "Tahini and olive oil provide heart-healthy monounsaturated fats and bone-supporting calcium.",
                "Rich in folate, iron, and manganese essential for energy production and immune health.",
                "Studies link regular consumption to improved gut microbiome diversity and lower inflammatory markers.",
            ],
            "it": [
                "Ricco di proteine vegetali e fibre dei ceci, favorendo il senso di sazietà e una glicemia stabile.",
                "Tahini e olio d'oliva forniscono grassi monoinsaturi salutari per il cuore e calcio a supporto delle ossa.",
                "Ricco di folati, ferro e manganese essenziali per la produzione di energia e la salute immunitaria.",
                "Studi associano il consumo regolare a una migliore diversità del microbioma e a marcatori infiammatori più bassi.",
            ],
            "es": [
                "Rico en proteína vegetal y fibra del garbanzo, favoreciendo la saciedad y el azúcar en sangre estable.",
                "El tahini y el aceite de oliva aportan grasas monoinsaturadas saludables para el corazón y calcio para los huesos.",
                "Rico en folato, hierro y manganeso esenciales para la energía y la salud inmunitaria.",
                "Estudios asocian el consumo regular con mayor diversidad del microbioma y menores marcadores inflamatorios.",
            ],
            "fr": [
                "Riche en protéines végétales et en fibres des pois chiches, favorisant la satiété et une glycémie stable.",
                "Le tahini et l'huile d'olive apportent des graisses monoinsaturées bénéfiques pour le cœur et du calcium pour les os.",
                "Riche en folate, fer et manganèse essentiels à la production d'énergie et à la santé immunitaire.",
                "Des études associent sa consommation régulière à une meilleure diversité du microbiome et des marqueurs inflammatoires réduits.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "hummus bowl dinner"},
            "salad": {"source_id": "eatingwell", "query": "hummus salad dressing"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "hummus eggs toast breakfast"},
        },
    },
    {
        "id": "dark_chocolate",
        "emoji": "🍫",
        "name": {"ru": "Тёмный шоколад", "en": "Dark chocolate", "it": "Cioccolato fondente", "es": "Chocolate negro", "fr": "Chocolat noir"},
        "benefits": {
            "ru": [
                "Богат флаванолами — катехинами и эпикатехином — улучшающими кровоток и снижающими давление.",
                "Умеренное регулярное употребление связывают со снижением риска сердечно-сосудистых заболеваний в нескольких крупных исследованиях.",
                "Содержит теобромин и небольшое количество кофеина, улучшающих концентрацию и настроение.",
                "Хороший источник магния, железа, меди и марганца для выработки энергии и антиоксидантной защиты.",
            ],
            "en": [
                "Rich in flavanols — catechins and epicatechin — that improve blood flow and lower blood pressure.",
                "Regular moderate consumption is associated with reduced risk of heart disease in multiple large studies.",
                "Contains theobromine and small amounts of caffeine that improve alertness and mood.",
                "Good source of magnesium, iron, copper, and manganese supporting energy and antioxidant defense.",
            ],
            "it": [
                "Ricco di flavanoli — catechine ed epicatechina — che migliorano il flusso sanguigno e abbassano la pressione.",
                "Il consumo moderato regolare è associato a un ridotto rischio di malattie cardiache in diversi grandi studi.",
                "Contiene teobromina e piccole quantità di caffeina che migliorano la lucidità mentale e l'umore.",
                "Buona fonte di magnesio, ferro, rame e manganese per l'energia e le difese antiossidanti.",
            ],
            "es": [
                "Rico en flavanoles — catequinas y epicatequina — que mejoran el flujo sanguíneo y reducen la presión arterial.",
                "El consumo moderado regular se asocia con menor riesgo de enfermedades cardíacas en múltiples grandes estudios.",
                "Contiene teobromina y pequeñas cantidades de cafeína que mejoran la concentración y el estado de ánimo.",
                "Buena fuente de magnesio, hierro, cobre y manganeso para la energía y la defensa antioxidante.",
            ],
            "fr": [
                "Riche en flavanols — catéchines et épicatéchine — qui améliorent la circulation et abaissent la pression artérielle.",
                "Une consommation modérée régulière est associée à un risque réduit de maladies cardiaques dans plusieurs grandes études.",
                "Contient de la théobromine et de petites quantités de caféine qui améliorent l'éveil et l'humeur.",
                "Bonne source de magnésium, fer, cuivre et manganèse pour l'énergie et les défenses antioxydantes.",
            ],
        },
        "recipes": {
            "main": {"source_id": "bbcgoodfood", "query": "dark chocolate mole sauce dinner"},
            "salad": {"source_id": "eatingwell", "query": "dark chocolate berry salad"},
            "breakfast": {"source_id": "eatingwell", "query": "dark chocolate breakfast recipes"},
        },
    },
    {
        "id": "olives",
        "emoji": "🫒",
        "name": {"ru": "Маслины/Оливки", "en": "Olives", "it": "Olive", "es": "Aceitunas", "fr": "Olives"},
        "benefits": {
            "ru": [
                "Богаты олеиновой кислотой — мононенасыщенным жиром, которому оливковое масло обязано своей кардиозащитной репутацией.",
                "Содержат олеуропеин — мощный полифенол с противовоспалительными, антиоксидантными и антимикробными свойствами.",
                "Хороший источник витамина E и железа для иммунной функции и транспорта кислорода.",
                "Регулярное употребление оливок — основа средиземноморской диеты, связанной с долголетием и снижением хронических заболеваний.",
            ],
            "en": [
                "Rich in oleic acid, the monounsaturated fat that gives olive oil its heart-protective reputation.",
                "Contain oleuropein, a powerful polyphenol with anti-inflammatory, antioxidant, and antimicrobial properties.",
                "Good source of vitamin E and iron supporting immune function and oxygen transport.",
                "Regular olive consumption is a cornerstone of the Mediterranean diet, linked to longevity and reduced chronic disease.",
            ],
            "it": [
                "Ricche di acido oleico, il grasso monoinsaturo a cui l'olio d'oliva deve la sua reputazione cardioprotettiva.",
                "Contengono oleuropeina, un potente polifenolo con proprietà antinfiammatorie, antiossidanti e antimicrobiche.",
                "Buona fonte di vitamina E e ferro per l'immunità e il trasporto dell'ossigeno.",
                "Il consumo regolare di olive è un pilastro della dieta mediterranea, associata a longevità e riduzione delle malattie croniche.",
            ],
            "es": [
                "Ricas en ácido oleico, la grasa monoinsaturada a la que el aceite de oliva debe su reputación cardioprotectora.",
                "Contienen oleuropeína, un potente polifenol con propiedades antiinflamatorias, antioxidantes y antimicrobianas.",
                "Buena fuente de vitamina E y hierro para la función inmunitaria y el transporte de oxígeno.",
                "El consumo regular de aceitunas es un pilar de la dieta mediterránea, asociada a la longevidad y la reducción de enfermedades crónicas.",
            ],
            "fr": [
                "Riches en acide oléique, la graisse monoinsaturée à laquelle l'huile d'olive doit sa réputation cardioprotectrice.",
                "Contiennent de l'oleuropéine, un puissant polyphénol aux propriétés anti-inflammatoires, antioxydantes et antimicrobiennes.",
                "Bonne source de vitamine E et de fer pour l'immunité et le transport de l'oxygène.",
                "La consommation régulière d'olives est un pilier du régime méditerranéen, associé à la longévité et à la réduction des maladies chroniques.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "olive tapenade pasta dinner"},
            "salad": {"source_id": "eatingwell", "query": "olive salad recipes"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "olive eggs breakfast"},
        },
    },
    {
        "id": "popcorn",
        "emoji": "🍿",
        "name": {"ru": "Попкорн (воздушный)", "en": "Popcorn", "it": "Popcorn", "es": "Palomitas de maíz", "fr": "Popcorn"},
        "benefits": {
            "ru": [
                "Воздушный попкорн — цельнозерновой продукт, содержащий больше клетчатки на калорию, чем большинство снеков.",
                "Один из богатейших цельнозерновых источников полифенольных антиоксидантов, сконцентрированных в шелухе.",
                "Очень мало калорий в воздушном попкорне — около 30 ккал на стакан — без добавленного жира.",
                "Содержит марганец, магний и витамины группы B для здоровья костей и энергетического обмена.",
            ],
            "en": [
                "Air-popped popcorn is a whole grain, providing more fiber per calorie than most snack foods.",
                "One of the richest whole grain sources of polyphenol antioxidants, concentrated in the hull.",
                "Very low in calories when air-popped — about 30 calories per cup — with no added fat.",
                "Provides manganese, magnesium, and B vitamins supporting bone health and energy metabolism.",
            ],
            "it": [
                "Il popcorn fatto ad aria è un cereale integrale, con più fibre per caloria rispetto alla maggior parte degli snack.",
                "Una delle fonti di cereali integrali più ricche di antiossidanti polifenoliche, concentrati nella buccia.",
                "Pochissime calorie quando fatto ad aria — circa 30 per tazza — senza grassi aggiunti.",
                "Fornisce manganese, magnesio e vitamine B per la salute ossea e il metabolismo energetico.",
            ],
            "es": [
                "Las palomitas de aire son un cereal integral que aporta más fibra por caloría que la mayoría de los snacks.",
                "Una de las fuentes de cereales integrales más ricas en antioxidantes polifenólicos, concentrados en la cáscara.",
                "Muy bajas en calorías cuando se hacen al aire — unas 30 kcal por taza — sin grasa añadida.",
                "Aporta manganeso, magnesio y vitaminas B para la salud ósea y el metabolismo energético.",
            ],
            "fr": [
                "Le popcorn soufflé à l'air est une céréale complète, apportant plus de fibres par calorie que la plupart des snacks.",
                "L'une des sources de céréales complètes les plus riches en antioxydants polyphénoliques, concentrés dans l'enveloppe.",
                "Très peu calorique soufflé à l'air — environ 30 calories par tasse — sans matières grasses ajoutées.",
                "Apporte du manganèse, du magnésium et des vitamines B pour la santé osseuse et le métabolisme énergétique.",
            ],
        },
        "recipes": {
            "main": {"source_id": "eatingwell", "query": "popcorn snack ideas"},
            "salad": {"source_id": "eatingwell", "query": "popcorn crouton salad"},
            "breakfast": {"source_id": "bbcgoodfood", "query": "popcorn sweet breakfast snack"},
        },
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────────────────────────────────────
SUPPORTED_LANGS = ("ru", "en", "it", "es", "fr")
_DEFAULT_LANG = "en"


def _norm_lang(lang: Optional[str]) -> str:
    lang = (lang or "").strip().lower()[:2]
    return lang if lang in SUPPORTED_LANGS else _DEFAULT_LANG


# Relative path (served by the backend under /static/potd/<id>.jpg). Clients
# join this onto the API origin. Kept relative so it works across environments.
_IMAGE_PATH = "/static/potd/{id}.jpg"


def _localize(product: dict, lang: str) -> dict:
    """Project a raw product record into a localized, client-ready dict."""
    recipes = {}
    for kind, spec in product["recipes"].items():
        recipes[kind] = _link(spec["source_id"], spec["query"])
    return {
        "id": product["id"],
        "emoji": product["emoji"],
        "image_url": _IMAGE_PATH.format(id=product["id"]),
        "name": product["name"].get(lang, product["name"][_DEFAULT_LANG]),
        "benefits": product["benefits"].get(lang, product["benefits"][_DEFAULT_LANG]),
        "recipes": recipes,
    }


def get_all_products(lang: str = _DEFAULT_LANG) -> list:
    lang = _norm_lang(lang)
    return [_localize(p, lang) for p in PRODUCTS]


def get_product_of_the_day(lang: str = _DEFAULT_LANG, day: Optional[datetime.date] = None) -> dict:
    """Return the localized product for `day` (defaults to today, UTC).

    Rotation is deterministic: day-of-year modulo the number of products, so
    everyone sees the same product on a given calendar day and it advances each
    day, cycling through the whole list.
    """
    lang = _norm_lang(lang)
    if day is None:
        day = datetime.datetime.utcnow().date()
    idx = (day.timetuple().tm_yday - 1) % len(PRODUCTS)
    product = _localize(PRODUCTS[idx], lang)
    product["date"] = day.isoformat()
    return product
