import os
import re
from collections import Counter

import fitz  # PyMuPDF
import streamlit as st
from google import genai


st.set_page_config(
    page_title="AI Study Buddy",
    page_icon="📚",
    layout="wide",
)

st.title("📚 AI Study Buddy")
st.write(
    "Upload your class notes or a PDF, then ask questions, generate quizzes, "
    "and create flashcards."
)


def get_api_key():
    """
    Reads the Gemini API key from Streamlit secrets first,
    then checks environment variables as a backup.
    """
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return os.getenv("GEMINI_API_KEY")


def extract_text_from_pdf(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    document = fitz.open(stream=file_bytes, filetype="pdf")

    text = ""

    for page_number, page in enumerate(document, start=1):
        page_text = page.get_text()
        text += f"\n\n--- Page {page_number} ---\n{page_text}"

    return text


def extract_text(uploaded_file):
    file_name = uploaded_file.name.lower()

    if file_name.endswith(".pdf"):
        return extract_text_from_pdf(uploaded_file)

    return uploaded_file.getvalue().decode("utf-8", errors="ignore")


def split_into_chunks(text, max_chars=1800):
    """
    Splits long notes into smaller chunks.
    This helps the app send only the most relevant parts to the AI.
    """
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        if len(current_chunk) + len(paragraph) > max_chars:
            if current_chunk.strip():
                chunks.append(current_chunk)
            current_chunk = paragraph
        else:
            current_chunk += "\n" + paragraph

    if current_chunk.strip():
        chunks.append(current_chunk)

    return chunks


def clean_words(text):
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())

    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "are", "was",
        "were", "you", "your", "have", "has", "had", "not", "but", "all",
        "can", "will", "would", "should", "about", "into", "than", "then",
        "also", "each", "when", "what", "where", "which", "why", "how"
    }

    return [word for word in words if word not in stopwords]


def find_relevant_chunks(question, chunks, top_k=3):
    """
    Simple keyword search.
    Later, we can upgrade this to a real vector search system.
    """
    question_words = Counter(clean_words(question))
    scored_chunks = []

    for chunk in chunks:
        chunk_words = Counter(clean_words(chunk))
        score = sum(
            question_words[word] * chunk_words[word]
            for word in question_words
        )
        scored_chunks.append((score, chunk))

    scored_chunks.sort(reverse=True, key=lambda item: item[0])

    best_chunks = [
        chunk
        for score, chunk in scored_chunks[:top_k]
        if score > 0
    ]

    if not best_chunks:
        return chunks[:top_k]

    return best_chunks


def ask_gemini(prompt):
    api_key = get_api_key()

    if not api_key:
        st.error(
            "Missing Gemini API key. Add GEMINI_API_KEY to "
            ".streamlit/secrets.toml."
        )
        return None

    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
        )
        return response.text

    except Exception as error:
        st.error("The AI request failed.")
        st.write(error)
        return None


uploaded_file = st.file_uploader(
    "Upload a PDF, text file, or Markdown file",
    type=["pdf", "txt", "md"],
)

if uploaded_file is None:
    st.info("Upload a file to begin.")
    st.stop()


notes_text = extract_text(uploaded_file)

if not notes_text.strip():
    st.warning("I could not extract text from this file. Try another PDF or a text file.")
    st.stop()


st.success(f"Uploaded: {uploaded_file.name}")

chunks = split_into_chunks(notes_text)

with st.expander("Preview extracted notes"):
    st.write(notes_text[:5000])

    if len(notes_text) > 5000:
        st.write("...preview shortened...")


tab1, tab2, tab3 = st.tabs(
    ["Ask Questions", "Generate Quiz", "Flashcards"]
)


with tab1:
    st.subheader("Ask a question about your notes")

    question = st.text_input(
        "Question",
        placeholder="Example: What are the main ideas in these notes?",
    )

    if st.button("Answer Question"):
        if not question.strip():
            st.warning("Type a question first.")
        else:
            relevant_chunks = find_relevant_chunks(question, chunks)
            context = "\n\n".join(relevant_chunks)

            prompt = f"""
You are an AI study tutor.

Answer the student's question using ONLY the notes below.

If the answer is not in the notes, say:
"I couldn't find that in your notes."

Student question:
{question}

Notes:
{context}

Answer in a clear, student-friendly way.
"""

            with st.spinner("Thinking..."):
                answer = ask_gemini(prompt)

            if answer:
                st.markdown(answer)


with tab2:
    st.subheader("Generate a practice quiz")

    quiz_type = st.selectbox(
        "Quiz type",
        ["Multiple choice", "Short answer", "Mixed"],
    )

    num_questions = st.slider(
        "Number of questions",
        min_value=3,
        max_value=10,
        value=5,
    )

    if st.button("Generate Quiz"):
        context = notes_text[:12000]

        prompt = f"""
You are an AI study tutor.

Create a {quiz_type.lower()} quiz using ONLY these notes.

Number of questions: {num_questions}

For each question:
- Write the question.
- Provide the correct answer.
- Add a short explanation.

Notes:
{context}
"""

        with st.spinner("Creating quiz..."):
            quiz = ask_gemini(prompt)

        if quiz:
            st.markdown(quiz)


with tab3:
    st.subheader("Generate flashcards")

    num_cards = st.slider(
        "Number of flashcards",
        min_value=5,
        max_value=20,
        value=10,
    )

    if st.button("Generate Flashcards"):
        context = notes_text[:12000]

        prompt = f"""
You are an AI study tutor.

Create {num_cards} flashcards from the notes below.

Format each flashcard like this:

Front: question or term
Back: answer or explanation

Use ONLY the notes.

Notes:
{context}
"""

        with st.spinner("Creating flashcards..."):
            flashcards = ask_gemini(prompt)

        if flashcards:
            st.markdown(flashcards)