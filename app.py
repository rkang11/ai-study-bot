import math
import os

import fitz  # PyMuPDF
import streamlit as st
from google import genai
from google.genai import types


st.set_page_config(
    page_title="AI Study Buddy",
    page_icon="📚",
    layout="wide",
)

st.title("📚 AI Study Buddy")
st.write(
    "Upload notes or choose a saved document, then ask questions, generate "
    "quizzes, and create flashcards."
)


def get_api_key():
    """
    Reads the Gemini API key from Streamlit secrets first,
    then checks environment variables as a backup.
    """
    return get_config_value("GEMINI_API_KEY")


def get_config_value(name):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name)


def get_gemini_client():
    api_key = get_api_key()

    if not api_key:
        st.error(
            "Missing Gemini API key. Add GEMINI_API_KEY to "
            ".streamlit/secrets.toml."
        )
        return None

    return genai.Client(api_key=api_key)


def get_supabase_client():
    url = get_config_value("SUPABASE_URL")
    anon_key = get_config_value("SUPABASE_ANON_KEY")

    if not url or not anon_key:
        return None

    if "supabase_client" in st.session_state:
        return st.session_state.supabase_client

    try:
        from supabase import create_client
    except ImportError:
        st.sidebar.warning("Install the supabase package to enable accounts.")
        return None

    st.session_state.supabase_client = create_client(url, anon_key)
    return st.session_state.supabase_client


def get_user_id(user):
    if user is None:
        return None

    if hasattr(user, "id"):
        return user.id

    return user.get("id")


def get_user_email(user):
    if user is None:
        return None

    if hasattr(user, "email"):
        return user.email

    return user.get("email")


def show_account_sidebar():
    with st.sidebar:
        st.header("Account")
        supabase = get_supabase_client()

        if supabase is None:
            st.caption(
                "Add SUPABASE_URL and SUPABASE_ANON_KEY to enable saved notes."
            )
            return None

        current_user = st.session_state.get("supabase_user")

        if current_user:
            st.success(f"Signed in as {get_user_email(current_user)}")

            if st.button("Sign out"):
                try:
                    supabase.auth.sign_out()
                except Exception:
                    pass

                st.session_state.pop("supabase_user", None)
                st.session_state.pop("saved_file_id", None)
                st.session_state.pop("saved_document_id", None)
                st.rerun()

            return current_user

        with st.form("account_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            auth_action = st.radio(
                "Action",
                ["Sign in", "Create account"],
                horizontal=True,
            )
            submitted = st.form_submit_button(auth_action)

        if submitted:
            if not email.strip() or not password:
                st.warning("Enter an email and password.")
                return None

            try:
                if auth_action == "Create account":
                    response = supabase.auth.sign_up(
                        {
                            "email": email.strip(),
                            "password": password,
                        }
                    )
                else:
                    response = supabase.auth.sign_in_with_password(
                        {
                            "email": email.strip(),
                            "password": password,
                        }
                    )

                if response.user:
                    st.session_state.supabase_user = response.user
                    st.rerun()

                st.info("Check your email to finish creating your account.")

            except Exception as error:
                st.error("Account request failed.")
                st.write(error)

        return None


def list_saved_documents(user):
    supabase = get_supabase_client()
    user_id = get_user_id(user)

    if supabase is None or not user_id:
        return []

    response = supabase.table("documents").select(
        "id, file_name, created_at"
    ).eq("user_id", user_id).order(
        "created_at",
        desc=True,
    ).limit(25).execute()

    return getattr(response, "data", None) or []


def rename_saved_document(user, document_id, new_file_name):
    supabase = get_supabase_client()
    user_id = get_user_id(user)

    if supabase is None or not user_id:
        return

    supabase.table("documents").update(
        {
            "file_name": new_file_name,
        }
    ).eq("id", document_id).eq("user_id", user_id).execute()


def delete_saved_document(user, document_id):
    supabase = get_supabase_client()
    user_id = get_user_id(user)

    if supabase is None or not user_id:
        return

    supabase.table("documents").delete().eq(
        "id",
        document_id,
    ).eq("user_id", user_id).execute()


def clear_active_saved_document(document_id):
    if st.session_state.get("saved_document_id") != document_id:
        return

    st.session_state.pop("saved_file_id", None)
    st.session_state.pop("saved_document_id", None)


def show_saved_documents_sidebar(user):
    if user is None or get_supabase_client() is None:
        return None

    with st.sidebar:
        st.header("Saved notes")

        try:
            documents = list_saved_documents(user)
        except Exception as error:
            error_text = str(error)

            if "PGRST205" in error_text or "schema cache" in error_text:
                st.warning(
                    "Saved notes are not set up yet. Run supabase_schema.sql "
                    "in the Supabase SQL editor, then refresh this app."
                )
            else:
                st.warning("Saved notes are not available yet.")
                st.write(error)

            return None

        if not documents:
            st.caption("Saved documents will appear here.")
            return None

        document_options = {"Upload new document": None}

        for document in documents:
            saved_date = document.get("created_at", "")[:10]
            label = f"{document['file_name']} · {saved_date}"
            document_options[label] = document["id"]

        selected_label = st.selectbox(
            "Study from",
            list(document_options.keys()),
        )

        selected_document_id = document_options[selected_label]

        if selected_document_id is None:
            return None

        selected_document = next(
            document
            for document in documents
            if document["id"] == selected_document_id
        )

        with st.expander("Manage selected note"):
            new_file_name = st.text_input(
                "Name",
                value=selected_document["file_name"],
            )

            if st.button("Rename note"):
                cleaned_file_name = new_file_name.strip()

                if not cleaned_file_name:
                    st.warning("Enter a name first.")
                else:
                    try:
                        rename_saved_document(
                            user,
                            selected_document_id,
                            cleaned_file_name,
                        )
                        clear_active_saved_document(selected_document_id)
                        st.success("Saved note renamed.")
                        st.rerun()
                    except Exception as error:
                        st.error("Could not rename this note.")
                        st.write(error)

            confirm_delete = st.checkbox(
                "I understand this will delete the saved note."
            )

            if st.button("Delete note", disabled=not confirm_delete):
                try:
                    delete_saved_document(user, selected_document_id)
                    clear_active_saved_document(selected_document_id)
                    st.success("Saved note deleted.")
                    st.rerun()
                except Exception as error:
                    st.error("Could not delete this note.")
                    st.write(error)

        return selected_document_id


def parse_pgvector_embedding(value):
    if isinstance(value, list):
        return value

    if isinstance(value, str):
        clean_value = value.strip().removeprefix("[").removesuffix("]")

        if not clean_value:
            return []

        return [float(item) for item in clean_value.split(",")]

    return value


def load_saved_document(document_id):
    supabase = get_supabase_client()

    document_response = supabase.table("documents").select(
        "id, file_name, char_count"
    ).eq("id", document_id).single().execute()
    document = getattr(document_response, "data", None)

    if not document:
        raise ValueError("Could not load the saved document.")

    chunks_response = supabase.table("document_chunks").select(
        "chunk_index, page_number, chunk_text, embedding"
    ).eq("document_id", document_id).order(
        "chunk_index",
    ).execute()
    chunk_rows = getattr(chunks_response, "data", None) or []

    indexed_chunks = []

    for row in chunk_rows:
        indexed_chunks.append(
            {
                "source": document["file_name"],
                "page_number": row["page_number"],
                "text": row["chunk_text"],
                "embedding": parse_pgvector_embedding(row["embedding"]),
            }
        )

    notes_text = "\n\n".join(chunk["text"] for chunk in indexed_chunks)

    return {
        "document_id": document["id"],
        "file_name": document["file_name"],
        "file_id": f"saved:{document['id']}",
        "notes_text": notes_text,
        "indexed_chunks": indexed_chunks,
    }


def extract_pages_from_pdf(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    document = fitz.open(stream=file_bytes, filetype="pdf")

    pages = []

    for page_number, page in enumerate(document, start=1):
        page_text = page.get_text()
        pages.append(
            {
                "page_number": page_number,
                "text": page_text,
            }
        )

    return pages


def extract_pages(uploaded_file):
    file_name = uploaded_file.name.lower()

    if file_name.endswith(".pdf"):
        return extract_pages_from_pdf(uploaded_file)

    text = uploaded_file.getvalue().decode("utf-8", errors="ignore")
    return [
        {
            "page_number": None,
            "text": text,
        }
    ]


def split_text_into_chunks(text, max_chars=1800):
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


def build_chunks(pages, source_name):
    chunks = []

    for page in pages:
        for chunk_text in split_text_into_chunks(page["text"]):
            chunks.append(
                {
                    "source": source_name,
                    "page_number": page["page_number"],
                    "text": chunk_text,
                }
            )

    return chunks


def extract_embedding_values(response):
    if getattr(response, "embeddings", None):
        return list(response.embeddings[0].values)

    if getattr(response, "embedding", None):
        return list(response.embedding.values)

    raise ValueError("Gemini did not return an embedding.")


def create_embedding(client, text):
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=768),
    )
    return extract_embedding_values(response)


def cosine_similarity(first_embedding, second_embedding):
    dot_product = sum(
        first_value * second_value
        for first_value, second_value in zip(first_embedding, second_embedding)
    )
    first_magnitude = math.sqrt(
        sum(value * value for value in first_embedding)
    )
    second_magnitude = math.sqrt(
        sum(value * value for value in second_embedding)
    )

    if first_magnitude == 0 or second_magnitude == 0:
        return 0

    return dot_product / (first_magnitude * second_magnitude)


def build_vector_index(chunks):
    client = get_gemini_client()

    if client is None:
        return None

    indexed_chunks = []

    try:
        for chunk in chunks:
            indexed_chunks.append(
                {
                    **chunk,
                    "embedding": create_embedding(client, chunk["text"]),
                }
            )

    except Exception as error:
        st.error("The embedding request failed.")
        st.write(error)
        return None

    return indexed_chunks


def find_relevant_chunks(question, indexed_chunks, top_k=4):
    client = get_gemini_client()

    if client is None:
        return []

    try:
        question_embedding = create_embedding(client, question)
    except Exception as error:
        st.error("The question embedding request failed.")
        st.write(error)
        return []

    scored_chunks = []

    for chunk in indexed_chunks:
        score = cosine_similarity(question_embedding, chunk["embedding"])
        scored_chunks.append((score, chunk))

    scored_chunks.sort(reverse=True, key=lambda item: item[0])
    return [chunk for score, chunk in scored_chunks[:top_k]]


def format_context(chunks):
    context_blocks = []

    for index, chunk in enumerate(chunks, start=1):
        page_label = (
            f"Page {chunk['page_number']}"
            if chunk["page_number"]
            else "Uploaded text"
        )
        context_blocks.append(
            f"[Note section {index} | {chunk['source']} | {page_label}]\n"
            f"{chunk['text']}"
        )

    return "\n\n".join(context_blocks)


def make_snippet(text, max_chars=350):
    clean_text = " ".join(text.split())

    if len(clean_text) <= max_chars:
        return clean_text

    return clean_text[:max_chars].rsplit(" ", 1)[0] + "..."


def show_relevant_note_sections(chunks):
    with st.expander("Relevant note sections"):
        for index, chunk in enumerate(chunks, start=1):
            page_label = (
                f"Page {chunk['page_number']}"
                if chunk["page_number"]
                else "Uploaded text"
            )
            st.markdown(
                f"**Note section {index}** · {chunk['source']} · {page_label}"
            )
            st.write(make_snippet(chunk["text"]))


def get_file_type(file_name):
    return file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "text"


def format_embedding_for_pgvector(embedding):
    return "[" + ",".join(str(value) for value in embedding) + "]"


def save_document_to_supabase(
    supabase,
    user,
    uploaded_file,
    notes_text,
    indexed_chunks,
):
    user_id = get_user_id(user)

    if not user_id:
        st.error("Sign in before saving this document.")
        return None

    document_response = supabase.table("documents").insert(
        {
            "user_id": user_id,
            "file_name": uploaded_file.name,
            "file_type": get_file_type(uploaded_file.name),
            "char_count": len(notes_text),
        }
    ).execute()

    document_rows = getattr(document_response, "data", None)

    if not document_rows:
        raise ValueError("Supabase did not return the saved document.")

    document_id = document_rows[0]["id"]
    chunk_rows = []

    for index, chunk in enumerate(indexed_chunks):
        chunk_rows.append(
            {
                "document_id": document_id,
                "user_id": user_id,
                "chunk_index": index,
                "page_number": chunk["page_number"],
                "chunk_text": chunk["text"],
                "embedding": format_embedding_for_pgvector(chunk["embedding"]),
            }
        )

    supabase.table("document_chunks").insert(chunk_rows).execute()
    return document_id


def show_save_document_controls(
    current_user,
    uploaded_file,
    file_id,
    notes_text,
    indexed_chunks,
):
    if current_user is None:
        st.caption("Sign in from the sidebar to save this document.")
        return

    if st.session_state.get("saved_file_id") == file_id:
        st.success("This document is saved.")
        return

    if st.button("Save this document"):
        supabase = get_supabase_client()

        if supabase is None:
            st.error("Supabase is not configured yet.")
            return

        try:
            with st.spinner("Saving document..."):
                document_id = save_document_to_supabase(
                    supabase,
                    current_user,
                    uploaded_file,
                    notes_text,
                    indexed_chunks,
                )

            st.session_state.saved_file_id = file_id
            st.session_state.saved_document_id = document_id
            st.success("Document saved.")

        except Exception as error:
            st.error("Could not save this document.")
            st.write(error)


def get_current_saved_document_id(file_id):
    if st.session_state.get("saved_file_id") != file_id:
        return None

    return st.session_state.get("saved_document_id")


def save_quiz_to_supabase(user, document_id, quiz_type, content):
    supabase = get_supabase_client()
    user_id = get_user_id(user)

    if supabase is None or not user_id or not document_id:
        return False

    supabase.table("quizzes").insert(
        {
            "document_id": document_id,
            "user_id": user_id,
            "quiz_type": quiz_type,
            "content": content,
        }
    ).execute()

    return True


def save_flashcards_to_supabase(user, document_id, content):
    supabase = get_supabase_client()
    user_id = get_user_id(user)

    if supabase is None or not user_id or not document_id:
        return False

    supabase.table("flashcards").insert(
        {
            "document_id": document_id,
            "user_id": user_id,
            "content": content,
        }
    ).execute()

    return True


def ask_gemini(prompt):
    client = get_gemini_client()

    if client is None:
        return None

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


current_user = show_account_sidebar()
selected_saved_document_id = show_saved_documents_sidebar(current_user)

uploaded_file = st.file_uploader(
    "Upload a PDF, text file, or Markdown file",
    type=["pdf", "txt", "md"],
)

if selected_saved_document_id:
    try:
        saved_document = load_saved_document(selected_saved_document_id)
    except Exception as error:
        st.error("Could not load this saved document.")
        st.write(error)
        st.stop()

    notes_text = saved_document["notes_text"]
    indexed_chunks = saved_document["indexed_chunks"]
    file_id = saved_document["file_id"]
    st.session_state.saved_file_id = file_id
    st.session_state.saved_document_id = saved_document["document_id"]
    st.success(f"Loaded saved document: {saved_document['file_name']}")

elif uploaded_file is not None:
    pages = extract_pages(uploaded_file)
    notes_text = "\n\n".join(page["text"] for page in pages)

    if not notes_text.strip():
        st.warning(
            "I could not extract text from this file. Try another PDF or a text file."
        )
        st.stop()

    st.success(f"Uploaded: {uploaded_file.name}")

    chunks = build_chunks(pages, uploaded_file.name)
    file_id = f"{uploaded_file.name}:{len(uploaded_file.getvalue())}"

    if st.session_state.get("indexed_file_id") != file_id:
        with st.spinner("Creating semantic search index..."):
            indexed_chunks = build_vector_index(chunks)

        if indexed_chunks:
            st.session_state.indexed_chunks = indexed_chunks
            st.session_state.indexed_file_id = file_id
        else:
            st.session_state.indexed_chunks = None

    indexed_chunks = st.session_state.get("indexed_chunks")

    if not indexed_chunks:
        st.stop()

    show_save_document_controls(
        current_user,
        uploaded_file,
        file_id,
        notes_text,
        indexed_chunks,
    )

else:
    st.info("Upload a file to begin.")
    st.stop()

if not indexed_chunks:
    st.stop()

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
            relevant_chunks = find_relevant_chunks(question, indexed_chunks)
            context = format_context(relevant_chunks)

            prompt = f"""
You are an AI study tutor.

Answer the student's question using ONLY the retrieved notes below.

If the answer is not in the notes, say:
"I couldn't find that in your notes."

Student question:
{question}

Notes:
{context}

Answer in a clear, student-friendly way. When you use information from a note
section, cite it with the note section label, such as [Note section 1].
"""

            with st.spinner("Thinking..."):
                answer = ask_gemini(prompt)

            if answer:
                st.markdown(answer)
                show_relevant_note_sections(relevant_chunks)


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

            document_id = get_current_saved_document_id(file_id)

            if document_id:
                try:
                    save_quiz_to_supabase(
                        current_user,
                        document_id,
                        quiz_type,
                        quiz,
                    )
                    st.success("Quiz saved.")
                except Exception as error:
                    st.warning("The quiz was generated, but could not be saved.")
                    st.write(error)
            elif current_user:
                st.caption("Save this document first to save generated quizzes.")


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

            document_id = get_current_saved_document_id(file_id)

            if document_id:
                try:
                    save_flashcards_to_supabase(
                        current_user,
                        document_id,
                        flashcards,
                    )
                    st.success("Flashcards saved.")
                except Exception as error:
                    st.warning(
                        "The flashcards were generated, but could not be saved."
                    )
                    st.write(error)
            elif current_user:
                st.caption(
                    "Save this document first to save generated flashcards."
                )
