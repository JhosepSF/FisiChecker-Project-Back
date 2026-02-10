# texts de link poco significativos
BAD_LINK_TEXT = {
    "click here","clickhere","here","aquí","leer más","read more",
    "más","ver más","ver mas","more"
}

# WCAG 1.3.5 Identify Input Purpose (AA)
AUTOCOMPLETE_TOKENS = {
    "name","honorific-prefix","given-name","additional-name","family-name",
    "honorific-suffix","nickname","email","username","new-password","current-password",
    "organization-title","organization","street-address","address-line1","address-line2",
    "address-line3","address-level4","address-level3","address-level2","address-level1",
    "country","country-name","postal-code","cc-name","cc-given-name","cc-additional-name",
    "cc-family-name","cc-number","cc-exp","cc-exp-month","cc-exp-year","cc-csc","cc-type",
    "transaction-currency","transaction-amount","language","bday","bday-day","bday-month",
    "bday-year","sex","tel","tel-country-code","tel-national","tel-area-code","tel-local",
    "tel-local-prefix","tel-local-suffix","tel-extension","impp","url","photo","one-time-code"
}

# Metadata para ponderar/filtrar por nivel y agrupar por principio (en ES)
WCAG_META = {
    # 1.x Perceptible
    "1.1.1": {"level": "A",   "principle": "Perceptible"},
    
    "1.2.1": {"level": "A",   "principle": "Perceptible"},
    "1.2.2": {"level": "A",   "principle": "Perceptible"},
    "1.2.3": {"level": "A",   "principle": "Perceptible"},
    "1.2.4": {"level": "AA",  "principle": "Perceptible"},
    "1.2.5": {"level": "AA",  "principle": "Perceptible"},
    "1.2.6": {"level": "AAA", "principle": "Perceptible"},
    "1.2.7": {"level": "AAA", "principle": "Perceptible"},
    "1.2.8": {"level": "AAA", "principle": "Perceptible"},
    "1.2.9": {"level": "AAA", "principle": "Perceptible"},
    
    "1.3.1": {"level": "A",   "principle": "Perceptible"},
    "1.3.2": {"level": "A",   "principle": "Perceptible"},
    "1.3.3": {"level": "A",   "principle": "Perceptible"},
    "1.3.4": {"level": "AA",  "principle": "Perceptible"},
    "1.3.5": {"level": "AA",  "principle": "Perceptible"},
    "1.3.6": {"level": "AAA", "principle": "Perceptible"},
    
    "1.4.1": {"level": "A",   "principle": "Perceptible"},
    "1.4.2": {"level": "A",   "principle": "Perceptible"},
    "1.4.3": {"level": "AA",  "principle": "Perceptible"},
    "1.4.4": {"level": "AA",  "principle": "Perceptible"},
    "1.4.5": {"level": "AA",  "principle": "Perceptible"},
    "1.4.6": {"level": "AAA", "principle": "Perceptible"},
    "1.4.7": {"level": "AAA", "principle": "Perceptible"},
    "1.4.8": {"level": "AAA", "principle": "Perceptible"},
    "1.4.9": {"level": "AAA", "principle": "Perceptible"},
    "1.4.10": {"level": "AA", "principle": "Perceptible"},
    "1.4.11": {"level": "AA", "principle": "Perceptible"},
    "1.4.12": {"level": "AA", "principle": "Perceptible"},
    "1.4.13": {"level": "AA", "principle": "Perceptible"},

    # 2.x Operable
    "2.1.1": {"level": "A",   "principle": "Operable"},
    "2.1.2": {"level": "A",   "principle": "Operable"},
    "2.1.3": {"level": "AAA", "principle": "Operable"},
    "2.1.4": {"level": "A",   "principle": "Operable"},

    "2.2.1": {"level": "A",   "principle": "Operable"},
    "2.2.2": {"level": "A",   "principle": "Operable"},
    "2.2.3": {"level": "AAA", "principle": "Operable"},
    "2.2.4": {"level": "AAA", "principle": "Operable"},
    "2.2.5": {"level": "AAA", "principle": "Operable"},
    "2.2.6": {"level": "AAA", "principle": "Operable"},

    "2.3.1": {"level": "A",   "principle": "Operable"},
    "2.3.2": {"level": "AAA", "principle": "Operable"},
    "2.3.3": {"level": "AAA", "principle": "Operable"},

    "2.4.1": {"level": "A",   "principle": "Operable"},
    "2.4.2": {"level": "A",   "principle": "Operable"},
    "2.4.3": {"level": "A",   "principle": "Operable"},
    "2.4.4": {"level": "A",   "principle": "Operable"},
    "2.4.5": {"level": "AA",  "principle": "Operable"},
    "2.4.6": {"level": "AA",  "principle": "Operable"},
    "2.4.7": {"level": "AA",  "principle": "Operable"},
    "2.4.8": {"level": "AAA", "principle": "Operable"},
    "2.4.9": {"level": "AAA", "principle": "Operable"},
    "2.4.10": {"level": "AAA","principle": "Operable"},

    "2.5.1": {"level": "A",   "principle": "Operable"},
    "2.5.2": {"level": "A",   "principle": "Operable"},
    "2.5.3": {"level": "A",   "principle": "Operable"},
    "2.5.4": {"level": "A",   "principle": "Operable"},
    "2.5.5": {"level": "AAA", "principle": "Operable"},
    "2.5.6": {"level": "AAA", "principle": "Operable"},
    
    # 3.x Comprensible
    "3.1.1": {"level": "A",   "principle": "Comprensible"},
    "3.1.2": {"level": "AA",  "principle": "Comprensible"},
    "3.1.3": {"level": "AAA", "principle": "Comprensible"},
    "3.1.4": {"level": "AAA", "principle": "Comprensible"},
    "3.1.5": {"level": "AAA", "principle": "Comprensible"},
    "3.1.6": {"level": "AAA", "principle": "Comprensible"},

    "3.2.1": {"level": "A",   "principle": "Comprensible"},
    "3.2.2": {"level": "A",   "principle": "Comprensible"},
    "3.2.3": {"level": "AA",  "principle": "Comprensible"},
    "3.2.4": {"level": "AA",  "principle": "Comprensible"},
    "3.2.5": {"level": "AAA", "principle": "Comprensible"},

    "3.3.1": {"level": "A",   "principle": "Comprensible"},
    "3.3.2": {"level": "A",   "principle": "Comprensible"},
    "3.3.3": {"level": "AA",  "principle": "Comprensible"},
    "3.3.4": {"level": "AA",  "principle": "Comprensible"},
    "3.3.5": {"level": "AAA", "principle": "Comprensible"},
    "3.3.6": {"level": "AAA", "principle": "Comprensible"},

    # 4.x Robusto
    "4.1.1": {"level": "A",  "principle": "Robusto"},
    "4.1.2": {"level": "A",  "principle": "Robusto"},
    "4.1.3": {"level": "AA", "principle": "Robusto"},
}
