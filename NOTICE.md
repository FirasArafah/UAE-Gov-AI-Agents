# Notice: third-party documents

The MIT License in [LICENSE](LICENSE) covers the Mawthuq code and the SYNORA team's own files:
the scenarios, the agent prompts, the retrieval test set and the knowledge base metadata.

It does **not** cover the source documents in `data/knowledge_base/raw` (113 files). They are
published by the organisations listed below, remain their property and are subject to their
publishers' own terms. They are included unchanged, or as plain-text copies of public web
pages, only as reference material for the knowledge base, so that the agents can quote and cite
them. Anyone reusing them should consult the publisher's terms.

Excerpts of these documents also appear in the knowledge base export produced by
`make export-kb`, which is subject to the same terms.

## United Arab Emirates

| Publisher | Documents |
|---|---|
| Federal Government of the UAE (official legislation) | The Constitution; Federal Decree-Laws No. 14 of 2021 (establishing the Federal Authority for Identity, Citizenship, Customs and Port Security), No. 29 of 2021 on Entry and Residence of Foreigners (Arabic and English), No. 33 of 2021 (Labour), No. 34 of 2021 (Rumours and Cybercrimes), No. 34 of 2023 (Combating Discrimination, Hatred and Extremism), No. 38 of 2021 (Copyright), No. 44 of 2021 (Emirates Data Office), No. 45 of 2021 on Personal Data Protection (Arabic and English); Cabinet Resolution No. 65 of 2022 (Arabic and English) |
| UAE Government (national strategies and guidance) | National Strategy for Artificial Intelligence 2031; UAE Charter for the Development and Use of Artificial Intelligence; AI Ethics Guidelines; Digital Government Strategy 2025; Digital Economy Strategy; Energy Strategy 2050 |
| Telecommunications and Digital Government Regulatory Authority (TDRA) | National Cybersecurity Strategy 2019 (strategy document and official summary) |
| UAE Government Portal, [u.ae](https://u.ae) | 83 official pages on strategies, programmes, government institutions and rights, saved as text by `scripts/fetch_portal_pages.py` (files named `UAE_Portal_*.txt`) |

## International and other references

| Publisher | Document |
|---|---|
| International Telecommunication Union (ITU) | Recommendation ITU-T Y.3172, *Architectural framework for machine learning in future networks including IMT-2020*; *AI Ready: Analysis Towards a Standardized Readiness Framework* (Report 2.0) |
| European Union | Regulation (EU) 2024/1689 (Artificial Intelligence Act), from the Official Journal of the European Union |
| Organisation for Economic Co-operation and Development (OECD) | Recommendation of the Council on Artificial Intelligence (OECD/LEGAL/0449) |
| United Nations Educational, Scientific and Cultural Organization (UNESCO) | Recommendation on the Ethics of Artificial Intelligence (2021), Arabic and English |
| Council of Europe | Framework Convention on Artificial Intelligence and Human Rights, Democracy and the Rule of Law (CETS No. 225) |
| National Institute of Standards and Technology (NIST), United States | AI Risk Management Framework (AI RMF 1.0, NIST AI 100-1) |
| Infocomm Media Development Authority and Personal Data Protection Commission, Singapore | Model AI Governance Framework, Second Edition |

The scenario in `data/scenarios` is fictional: its incident, figures and screening system do not
describe any real system or decision.
