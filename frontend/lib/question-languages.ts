export const QUESTION_LANGUAGES = {
  en: {
    label: 'English', name: 'English', htmlLang: 'en',
    greeting: 'Hi, I’m Fomy. I’ll help you fill out your form, one small question at a time. Ready to start?',
    ready: 'Your answers are ready to review.', resume: 'Let’s continue with the question we were working on.',
  },
  es: {
    label: 'Español (Spanish)', name: 'Spanish', htmlLang: 'es',
    greeting: 'Hola, soy Fomy. Te ayudaré a completar tu formulario, una pregunta a la vez. ¿Empezamos?',
    ready: 'Tus respuestas están listas para revisar.', resume: 'Continuemos con la pregunta anterior.',
  },
  zh: {
    label: '中文 (Chinese)', name: 'Simplified Chinese (Mandarin)', htmlLang: 'zh-Hans',
    greeting: '你好，我是 Fomy。我会一步一步帮你填写表格，一次回答一个简单的问题。我们开始吧？',
    ready: '你的回答已准备好，可以检查了。', resume: '我们继续回答刚才的问题吧。',
  },
  fil: {
    label: 'Tagalog', name: 'Tagalog (Filipino)', htmlLang: 'fil',
    greeting: 'Kumusta, ako si Fomy. Tutulungan kitang sagutan ang form, isang simpleng tanong sa bawat pagkakataon. Magsimula na tayo?',
    ready: 'Maaari mo nang suriin ang mga sagot mo.', resume: 'Ituloy natin ang tanong na sinasagutan natin.',
  },
  vi: {
    label: 'Tiếng Việt (Vietnamese)', name: 'Vietnamese', htmlLang: 'vi',
    greeting: 'Xin chào, tôi là Fomy. Tôi sẽ giúp bạn điền biểu mẫu, từng câu hỏi đơn giản một. Chúng ta bắt đầu nhé?',
    ready: 'Bạn có thể kiểm tra lại các câu trả lời.', resume: 'Chúng ta tiếp tục câu hỏi trước nhé.',
  },
  ar: {
    label: 'العربية (Arabic)', name: 'Modern Standard Arabic', htmlLang: 'ar',
    greeting: 'مرحبًا، أنا فومي. سأساعدك في ملء النموذج، بسؤال بسيط في كل مرة. هل نبدأ؟',
    ready: 'إجاباتك جاهزة للمراجعة.', resume: 'لنكمل السؤال الذي كنا نعمل عليه.',
  },
  fr: {
    label: 'Français (French)', name: 'French', htmlLang: 'fr',
    greeting: 'Bonjour, je suis Fomy. Je vais vous aider à remplir votre formulaire, une petite question à la fois. On commence ?',
    ready: 'Vos réponses sont prêtes à être vérifiées.', resume: 'Reprenons la question précédente.',
  },
  ko: {
    label: '한국어 (Korean)', name: 'Korean', htmlLang: 'ko',
    greeting: '안녕하세요, 저는 포미예요. 간단한 질문을 하나씩 하면서 양식 작성을 도와드릴게요. 시작할까요?',
    ready: '이제 답변을 검토할 수 있어요.', resume: '이전에 답하던 질문을 이어서 해 볼까요?',
  },
  pt: {
    label: 'Português (Portuguese)', name: 'Brazilian Portuguese', htmlLang: 'pt-BR',
    greeting: 'Olá, eu sou o Fomy. Vou ajudar você a preencher seu formulário, uma pergunta simples de cada vez. Vamos começar?',
    ready: 'Suas respostas estão prontas para revisão.', resume: 'Vamos continuar com a pergunta anterior.',
  },
  hi: {
    label: 'हिन्दी (Hindi)', name: 'Hindi', htmlLang: 'hi',
    greeting: 'नमस्ते, मैं फ़ोमी हूँ। मैं एक बार में एक आसान सवाल पूछकर आपका फ़ॉर्म भरने में मदद करूँगा। क्या हम शुरू करें?',
    ready: 'आपके जवाब जाँचने के लिए तैयार हैं।', resume: 'आइए, पिछले सवाल से आगे बढ़ते हैं।',
  },
} as const;

export type QuestionLanguage = keyof typeof QUESTION_LANGUAGES;
export function questionLanguage(value: unknown): QuestionLanguage {
  return typeof value === 'string' && Object.hasOwn(QUESTION_LANGUAGES, value) ? value as QuestionLanguage : 'en';
}

// The conversation SDK uses tl for Tagalog; the TTS API uses fil.
// Keep the form session's codes stable and adapt only at the voice boundary.
export function agentLanguage(language: QuestionLanguage) {
  return language === 'fil' ? 'tl' : language === 'pt' ? 'pt-br' : language;
}
