# AI Study Buddy

AI Study Buddy is a web app that helps students study from their own notes.

Users can upload a PDF, text file, or Markdown file, then ask questions, generate organized study notes, practice with interactive quizzes, create flashcards, and download study materials as PDFs.

The app uses a retrieval-augmented generation pipeline with Gemini embeddings to find the most relevant note sections before answering questions. Supabase adds user accounts, saved documents, persistent study notes, saved quizzes/flashcards, and pgvector-backed storage for document chunks.

Quizzes support multiple choice, short answer, and mixed modes with answer submission and feedback. Flashcards use a focused one-card-at-a-time viewer and can be exported with study notes and quizzes as printable PDFs.

The web app is hosted at [`https://ai-studying-tool.streamlit.app/`](https://ai-studying-tool.streamlit.app/)

## Tech Stack

- Python
- Streamlit - web interface
- Gemini API - generation, grading, and embeddings
- RAG - retrieval-augmented generation over uploaded notes
- pgvector - semantic search over embedded document chunks
- Supabase - authentication and backend platform
- PostgreSQL - persistent storage for documents, quizzes, flashcards, and study notes
- Supabase Row Level Security - user-scoped saved materials
- PyMuPDF - PDF text extraction and PDF export
- GitHub Actions - scheduled keep-alive workflow
