from forest.core.tool_registry import ToolRegistry


@ToolRegistry.register("medical_kb")
class MedicalKnowledgeTool:
    SYMPTOM_DATABASE: dict[str, list[dict[str, str]]] = {
        "headache": [
            {"condition": "Tension headache", "symptoms": "bilateral pressing pain, mild to moderate",
             "suggestion": "Rest, hydration, OTC pain relievers"},
            {"condition": "Migraine", "symptoms": "unilateral throbbing pain, photophobia, nausea",
             "suggestion": "Dark room rest, consult neurologist if severe"},
            {"condition": "Sinusitis", "symptoms": "facial pressure, nasal congestion, fever",
             "suggestion": "Decongestants, nasal irrigation, consult ENT if persistent"},
        ],
        "fever": [
            {"condition": "Common cold", "symptoms": "mild fever, runny nose, sore throat",
             "suggestion": "Rest, hydration, antipyretics as needed"},
            {"condition": "Influenza", "symptoms": "high fever, body aches, fatigue",
             "suggestion": "Antiviral medication within 48h, rest, monitor symptoms"},
            {"condition": "Bacterial infection", "symptoms": "persistent high fever, localized pain",
             "suggestion": "Consult physician, may require antibiotics"},
        ],
        "chest pain": [
            {"condition": "Angina", "symptoms": "chest pressure, radiating to left arm, exertion-induced",
             "suggestion": "Immediate medical evaluation, ECG required"},
            {"condition": "GERD", "symptoms": "burning sensation, worse after meals, lying down",
             "suggestion": "Antacids, dietary changes, consult gastroenterologist"},
            {"condition": "Costochondritis", "symptoms": "sharp pain, reproducible on palpation",
             "suggestion": "NSAIDs, rest, avoid strenuous activity"},
        ],
        "fatigue": [
            {"condition": "Anemia", "symptoms": "pale skin, shortness of breath, dizziness",
             "suggestion": "Blood test, iron supplementation if deficient"},
            {"condition": "Hypothyroidism", "symptoms": "weight gain, cold intolerance, dry skin",
             "suggestion": "Thyroid function test, hormone replacement therapy"},
            {"condition": "Sleep apnea", "symptoms": "daytime sleepiness, loud snoring, morning headache",
             "suggestion": "Sleep study, CPAP therapy if diagnosed"},
        ],
    }

    async def lookup_symptoms(self, symptom: str) -> list[dict[str, str]]:
        symptom = symptom.strip().lower()
        for key, conditions in self.SYMPTOM_DATABASE.items():
            if key == symptom or key in symptom or symptom in key:
                return conditions
        return [{"condition": "Unknown", "symptoms": symptom,
                 "suggestion": "Consult a physician for proper diagnosis"}]

    async def list_common_symptoms(self) -> list[str]:
        return list(self.SYMPTOM_DATABASE.keys())

    async def __call__(self, action: str, symptom: str = "") -> str:
        if action == "lookup":
            results = await self.lookup_symptoms(symptom)
            lines = [f"- **{r['condition']}**: {r['symptoms']} → {r['suggestion']}" for r in results]
            return "\n".join(lines)
        elif action == "list":
            symptoms = await self.list_common_symptoms()
            return "\n".join(f"- {s}" for s in symptoms)
        return f"Unknown action: {action}"
