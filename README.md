# AI Study Buddy

AI Study Buddy is a web app that helps students study from their own notes.

Users can upload a PDF, text file, or Markdown file, then ask questions, generate practice quizzes, and create flashcards using AI.

The app uses a retrieval-augmented generation pipeline with Gemini embeddings to find the most relevant note sections before answering questions. We also use supabase to add user accounts, saved documents, and persistent quizzes/flashcards.

The web app is hosted at [`https://ai-studying-tool.streamlit.app/`](https://ai-studying-tool.streamlit.app/)

## Tech Stack

- Python
- Streamlit - the web interface
- Gemini API - generation and embeddings
- PyMuPDF - PDF text extraction
- RAG (retrieval-augmented generation)
- Supabase - authentication, Postgres storage, and pgvector
