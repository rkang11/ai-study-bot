import math
import os
import json
import html
import re
import textwrap

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


def remember_supabase_user(auth_response):
    user = getattr(auth_response, "user", None)

    if user is not None:
        st.session_state.supabase_user = user


def clear_supabase_session_state():
    st.session_state.pop("supabase_user", None)
    st.session_state.pop("saved_file_id", None)
    st.session_state.pop("saved_document_id", None)
    st.session_state.pop("selected_saved_document_id", None)


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
            st.caption("Signed in")
            st.write(get_user_email(current_user))

            if st.button("Sign out", use_container_width=True):
                try:
                    supabase.auth.sign_out()
                except Exception:
                    pass

                clear_supabase_session_state()
                st.rerun()

            return current_user

        auth_action = st.radio(
            "Account action",
            ["Sign in", "Create account"],
            horizontal=True,
            label_visibility="collapsed",
        )

        with st.form("account_form"):
            email = st.text_input(
                "Email",
                placeholder="you@example.com",
            )
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Your password",
            )
            submitted = st.form_submit_button(
                auth_action,
                use_container_width=True,
                type="primary",
            )

        if auth_action == "Create account":
            st.caption("New accounts may require email confirmation.")

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
                    remember_supabase_user(response)
                    st.rerun()

                st.info("Check your email to finish creating your account.")

            except Exception as error:
                st.error("Account request failed.")
                st.caption(str(error))

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
    st.session_state.pop("selected_saved_document_id", None)


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

        selected_saved_document_id = st.session_state.get(
            "selected_saved_document_id"
        )
        default_index = 0

        if selected_saved_document_id:
            for index, document_id in enumerate(document_options.values()):
                if document_id == selected_saved_document_id:
                    default_index = index
                    break

        selected_label = st.selectbox(
            "Study from",
            list(document_options.keys()),
            index=default_index,
        )

        selected_document_id = document_options[selected_label]
        st.session_state.selected_saved_document_id = selected_document_id

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
        "id, file_name, char_count, study_notes"
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
        "study_notes": document.get("study_notes"),
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


def generate_study_notes(notes_text):
    context = notes_text[:12000]

    prompt = f"""
You are an AI study tutor.

Create organized study notes from the uploaded material below.

Use ONLY the material below.

Format the study notes in Markdown with clear headings:

## Overview
Briefly explain what the notes are about.

## Key Concepts
List the most important concepts with concise explanations. Bold key terms.

## Important Details
Organize supporting facts, examples, formulas, dates, names, or processes.

## Common Confusions
Point out ideas students might mix up and clarify the differences.

## Quick Review Questions
Write 5 short questions a student can use to check understanding.

Keep the notes easy to scan with short paragraphs and bullet points.

Material:
{context}
"""

    return ask_gemini(prompt)


def save_study_notes_to_supabase(user, document_id, study_notes):
    supabase = get_supabase_client()
    user_id = get_user_id(user)

    if supabase is None or not user_id or not document_id or not study_notes:
        return False

    supabase.table("documents").update(
        {
            "study_notes": study_notes,
        }
    ).eq("id", document_id).eq("user_id", user_id).execute()

    return True


def extract_markdown_section(markdown_text, heading):
    section_lines = []
    in_section = False
    target_heading = f"## {heading}".lower()

    for line in markdown_text.splitlines():
        clean_line = line.strip()

        if clean_line.lower() == target_heading:
            in_section = True
            continue

        if in_section and clean_line.startswith("## "):
            break

        if in_section:
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def show_study_notes(
    notes_text,
    file_id,
    current_user=None,
    document_id=None,
    saved_study_notes=None,
):
    cache_key = f"study_notes:{file_id}"
    saved_key = f"study_notes_saved:{file_id}"

    st.subheader("Study Notes")

    if saved_study_notes and cache_key not in st.session_state:
        st.session_state[cache_key] = saved_study_notes
        st.session_state[saved_key] = True

    if cache_key not in st.session_state:
        with st.spinner("Creating study notes..."):
            st.session_state[cache_key] = generate_study_notes(notes_text)

    study_notes = st.session_state.get(cache_key)

    if not study_notes:
        st.info("Study notes could not be generated yet.")
        return

    if document_id and not st.session_state.get(saved_key):
        try:
            if save_study_notes_to_supabase(
                current_user,
                document_id,
                study_notes,
            ):
                st.session_state[saved_key] = True
        except Exception as error:
            st.warning("Study notes were generated but could not be saved.")
            st.caption(str(error))

    overview = extract_markdown_section(study_notes, "Overview")

    with st.container(border=True):
        st.markdown("**Overview**")
        st.markdown(overview or make_snippet(study_notes, 700))

    with st.expander("View full study notes"):
        st.markdown(study_notes)

    st.download_button(
        "Download study notes PDF",
        data=create_study_notes_pdf(study_notes),
        file_name="study-notes.pdf",
        mime="application/pdf",
    )


def strip_markdown(text):
    clean_text = text.replace("**", "")
    clean_text = clean_text.replace("__", "")
    clean_text = clean_text.replace("`", "")
    clean_text = re.sub(r"^#{1,6}\s*", "", clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean_text)
    return clean_text


def add_pdf_page(document):
    return document.new_page(width=612, height=792)


def draw_wrapped_text(page, text, x, y, width, font_size=11, line_gap=4):
    max_chars = max(20, int(width / (font_size * 0.52)))
    lines = []

    for raw_line in str(text).splitlines():
        if not raw_line.strip():
            lines.append("")
            continue

        lines.extend(
            textwrap.wrap(
                raw_line,
                width=max_chars,
                replace_whitespace=False,
            )
        )

    line_height = font_size + line_gap

    for line in lines:
        if line:
            page.insert_text(
                (x, y),
                line,
                fontsize=font_size,
                fontname="helv",
                color=(0.1, 0.1, 0.1),
            )
        y += line_height

    return y


def parse_bold_segments(text):
    segments = []
    current_index = 0

    for match in re.finditer(r"\*\*(.+?)\*\*", text):
        if match.start() > current_index:
            segments.append((text[current_index:match.start()], False))

        segments.append((match.group(1), True))
        current_index = match.end()

    if current_index < len(text):
        segments.append((text[current_index:], False))

    return segments or [(text, False)]


def draw_rich_text_line(
    page,
    segments,
    x,
    y,
    width,
    font_size=11,
    line_gap=4,
):
    cursor_x = x
    max_x = x + width
    line_height = font_size + line_gap

    for text, is_bold in segments:
        font_name = "hebo" if is_bold else "helv"
        tokens = re.findall(r"\S+\s*", text)

        for token in tokens:
            token_width = fitz.get_text_length(
                token,
                fontname=font_name,
                fontsize=font_size,
            )

            if cursor_x > x and cursor_x + token_width > max_x:
                cursor_x = x
                y += line_height

            page.insert_text(
                (cursor_x, y),
                token,
                fontsize=font_size,
                fontname=font_name,
                color=(0.1, 0.1, 0.1),
            )
            cursor_x += token_width

    return y + line_height


def ensure_pdf_space(document, page, y, needed_space):
    if y + needed_space <= 740:
        return page, y

    return add_pdf_page(document), 60


def create_text_pdf(title, body):
    document = fitz.open()
    page = add_pdf_page(document)
    margin = 54
    y = 60

    page.insert_text(
        (margin, y),
        title,
        fontsize=20,
        fontname="helv",
        color=(0.05, 0.05, 0.05),
    )
    y += 36

    for paragraph in strip_markdown(body).split("\n\n"):
        if y > 720:
            page = add_pdf_page(document)
            y = 60

        y = draw_wrapped_text(page, paragraph, margin, y, 504)
        y += 12

    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def create_study_notes_pdf(study_notes):
    document = fitz.open()
    page = add_pdf_page(document)
    margin = 54
    y = 60

    page.insert_text(
        (margin, y),
        "Study Notes",
        fontsize=22,
        fontname="hebo",
        color=(0.05, 0.05, 0.05),
    )
    y += 38

    for raw_line in study_notes.splitlines():
        line = raw_line.rstrip()

        if not line.strip():
            y += 10
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)

        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2)
            font_size = 17 if level <= 2 else 14
            y += 8 if level <= 2 else 4
            page, y = ensure_pdf_space(document, page, y, 34)
            y = draw_rich_text_line(
                page,
                [(heading_text, True)],
                margin,
                y,
                504,
                font_size=font_size,
                line_gap=6,
            )
            y += 4
            continue

        bullet_match = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        numbered_match = re.match(r"^(\s*)(\d+\.)\s+(.*)$", line)

        if bullet_match:
            indent = min(len(bullet_match.group(1)) * 4, 36)
            content = bullet_match.group(2)
            page, y = ensure_pdf_space(document, page, y, 30)
            page.insert_text(
                (margin + indent, y),
                "-",
                fontsize=11,
                fontname="helv",
            )
            y = draw_rich_text_line(
                page,
                parse_bold_segments(content),
                margin + indent + 18,
                y,
                486 - indent,
            )
            continue

        if numbered_match:
            indent = min(len(numbered_match.group(1)) * 4, 36)
            label = numbered_match.group(2)
            content = numbered_match.group(3)
            page, y = ensure_pdf_space(document, page, y, 30)
            page.insert_text(
                (margin + indent, y),
                label,
                fontsize=11,
                fontname="helv",
            )
            y = draw_rich_text_line(
                page,
                parse_bold_segments(content),
                margin + indent + 26,
                y,
                478 - indent,
            )
            continue

        page, y = ensure_pdf_space(document, page, y, 30)
        y = draw_rich_text_line(
            page,
            parse_bold_segments(line),
            margin,
            y,
            504,
        )

    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def get_quiz_questions(quiz_data):
    if isinstance(quiz_data, dict):
        return quiz_data.get("questions", [])

    return []


def get_quiz_question_type(default_type, question):
    if default_type == "Multiple choice":
        return "multiple_choice"

    if default_type == "Short answer":
        return "short_answer"

    return question.get("type")


def create_quiz_pdf(quiz_type, quiz_data):
    questions = get_quiz_questions(quiz_data)
    document = fitz.open()
    page = add_pdf_page(document)
    margin = 54
    y = 60
    answers = []

    page.insert_text(
        (margin, y),
        f"{quiz_type} Quiz",
        fontsize=20,
        fontname="helv",
    )
    y += 36

    for index, question in enumerate(questions, start=1):
        question_type = get_quiz_question_type(quiz_type, question)

        if y > 680:
            page = add_pdf_page(document)
            y = 60

        y = draw_wrapped_text(
            page,
            f"{index}. {question.get('question', '')}",
            margin,
            y,
            504,
            font_size=12,
        )
        y += 6

        if question_type == "multiple_choice":
            choices = question.get("choices", [])

            for choice_index, choice in enumerate(choices):
                label = chr(ord("A") + choice_index)
                y = draw_wrapped_text(
                    page,
                    f"{label}. {choice}",
                    margin + 18,
                    y,
                    486,
                )

            try:
                answer_index = int(question.get("answer_index", 0))
            except (TypeError, ValueError):
                answer_index = 0

            if answer_index < len(choices):
                answer_label = chr(ord("A") + answer_index)
                answer_text = choices[answer_index]
                answers.append(f"{index}. {answer_label}. {answer_text}")
            else:
                answers.append(f"{index}. ")

            y += 12
        else:
            page.draw_rect(
                fitz.Rect(margin, y, margin + 504, y + 70),
                color=(0.55, 0.55, 0.55),
                width=0.8,
            )
            answers.append(f"{index}. {question.get('answer', '')}")
            y += 88

    page = add_pdf_page(document)
    y = 60
    page.insert_text((margin, y), "Answer Key", fontsize=20, fontname="helv")
    y += 36

    for answer in answers:
        if y > 720:
            page = add_pdf_page(document)
            y = 60

        y = draw_wrapped_text(page, answer, margin, y, 504)
        y += 8

    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def draw_flashcard_side(page, rect, text):
    page.draw_rect(rect, color=(0.35, 0.35, 0.35), width=1)
    draw_wrapped_text(
        page,
        text,
        rect.x0 + 18,
        rect.y0 + 34,
        rect.width - 36,
        font_size=12,
    )


def draw_flashcard_pair(page, top, index, front, back):
    page.insert_text(
        (54, top - 14),
        f"Card {index}",
        fontsize=11,
        fontname="hebo",
        color=(0.25, 0.25, 0.25),
    )
    front_rect = fitz.Rect(54, top, 300, top + 260)
    back_rect = fitz.Rect(312, top, 558, top + 260)
    draw_flashcard_side(page, front_rect, front)
    draw_flashcard_side(page, back_rect, back)


def create_flashcards_pdf(flashcards_data):
    flashcards = flashcards_data.get("flashcards", [])
    document = fitz.open()
    page = None

    for index, flashcard in enumerate(flashcards):
        if index % 2 == 0:
            page = add_pdf_page(document)
            page.insert_text((54, 42), "Flashcards", fontsize=18, fontname="helv")

        top = 92 if index % 2 == 0 else 432
        draw_flashcard_pair(
            page,
            top,
            index + 1,
            flashcard.get("front", ""),
            flashcard.get("back", ""),
        )

    if not flashcards:
        page = add_pdf_page(document)
        page.insert_text((54, 60), "No flashcards generated.", fontsize=12)

    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


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
    study_notes=None,
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
            "study_notes": study_notes,
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
                study_notes = st.session_state.get(f"study_notes:{file_id}")
                document_id = save_document_to_supabase(
                    supabase,
                    current_user,
                    uploaded_file,
                    notes_text,
                    indexed_chunks,
                    study_notes,
                )

            st.session_state.saved_file_id = file_id
            st.session_state.saved_document_id = document_id
            st.session_state.selected_saved_document_id = document_id
            if study_notes:
                st.session_state[f"study_notes_saved:saved:{document_id}"] = True
            st.success("Document saved.")
            st.rerun()

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


def extract_json_from_text(text):
    clean_text = text.strip()

    if clean_text.startswith("```"):
        clean_text = clean_text.removeprefix("```json").removeprefix("```")
        clean_text = clean_text.removesuffix("```").strip()

    start_index = clean_text.find("{")
    end_index = clean_text.rfind("}")

    if start_index == -1 or end_index == -1:
        raise ValueError("The quiz response did not contain JSON.")

    return json.loads(clean_text[start_index:end_index + 1])


def create_multiple_choice_prompt(notes_text, num_questions):
    context = notes_text[:12000]

    return f"""
You are an AI study tutor.

Create a multiple choice quiz using ONLY these notes.

Number of questions: {num_questions}

Return ONLY valid JSON with this exact structure:
{{
  "questions": [
    {{
      "question": "Question text",
      "choices": ["Choice A", "Choice B", "Choice C", "Choice D"],
      "answer_index": 0,
      "explanation": "Short explanation of why the answer is correct."
    }}
  ]
}}

Rules:
- Each question must have exactly 4 answer choices.
- answer_index must be the zero-based index of the correct choice.
- Do not include Markdown.
- Do not include answers in the question text.

Notes:
{context}
"""


def create_short_answer_prompt(notes_text, num_questions):
    context = notes_text[:12000]

    return f"""
You are an AI study tutor.

Create a short answer quiz using ONLY these notes.

Number of questions: {num_questions}

Return ONLY valid JSON with this exact structure:
{{
  "questions": [
    {{
      "question": "Question text",
      "answer": "Expected answer",
      "explanation": "Short explanation of the answer."
    }}
  ]
}}

Rules:
- Questions should require 1-3 sentence answers.
- Do not include Markdown.
- Do not reveal answers in the question text.

Notes:
{context}
"""


def create_mixed_quiz_prompt(notes_text, num_questions):
    context = notes_text[:12000]

    return f"""
You are an AI study tutor.

Create a mixed practice quiz using ONLY these notes.

Number of questions: {num_questions}

Return ONLY valid JSON with this exact structure:
{{
  "questions": [
    {{
      "type": "multiple_choice",
      "question": "Question text",
      "choices": ["Choice A", "Choice B", "Choice C", "Choice D"],
      "answer_index": 0,
      "explanation": "Short explanation of why the answer is correct."
    }},
    {{
      "type": "short_answer",
      "question": "Question text",
      "answer": "Expected answer",
      "explanation": "Short explanation of the answer."
    }}
  ]
}}

Rules:
- Include a balanced mix of multiple-choice and short-answer questions.
- Multiple-choice questions must have exactly 4 answer choices.
- Multiple-choice answer_index must be the zero-based index of the correct
  choice.
- Short-answer questions should require 1-3 sentence answers.
- Do not include Markdown.
- Do not reveal answers in the question text.

Notes:
{context}
"""


def create_short_answer_grade_prompt(question, expected_answer, student_answer):
    return f"""
You are an AI study tutor grading a short answer question.

Decide whether the student's answer is correct based on meaning, not exact
wording.

Return ONLY valid JSON with this exact structure:
{{
  "is_correct": true,
  "feedback": "Brief, student-friendly feedback."
}}

Question:
{question}

Expected answer:
{expected_answer}

Student answer:
{student_answer}
"""


def create_flashcards_prompt(notes_text, num_cards):
    context = notes_text[:12000]

    return f"""
You are an AI study tutor.

Create {num_cards} flashcards from the notes below.

Return ONLY valid JSON with this exact structure:
{{
  "flashcards": [
    {{
      "front": "Question or term",
      "back": "Answer or explanation"
    }}
  ]
}}

Rules:
- Use ONLY the notes.
- Keep front text short and focused.
- Make back text clear, accurate, and useful for studying.
- Do not include Markdown.

Notes:
{context}
"""


def render_multiple_choice_question(question, file_id, index, key_prefix="mc"):
    choices = question.get("choices", [])
    answer_index = question.get("answer_index")

    if len(choices) != 4 or answer_index not in range(4):
        st.warning("This multiple-choice question could not be displayed.")
        return

    submitted_key = f"{key_prefix}_submitted:{file_id}:{index}"
    selected_key = f"{key_prefix}_selected:{file_id}:{index}"

    st.markdown(f"**Question {index}**")
    st.write(question.get("question", ""))

    selected_choice = st.radio(
        "Answer choices",
        choices,
        key=selected_key,
        label_visibility="collapsed",
    )

    if st.button("Submit answer", key=f"{key_prefix}_submit:{file_id}:{index}"):
        st.session_state[submitted_key] = selected_choice

    submitted_choice = st.session_state.get(submitted_key)

    if submitted_choice is not None:
        correct_choice = choices[answer_index]

        if submitted_choice == correct_choice:
            st.success(f"Correct. Answer: {correct_choice}")
        else:
            st.error(f"Not quite. Correct answer: {correct_choice}")

        explanation = question.get("explanation")

        if explanation:
            st.write(explanation)


def render_short_answer_question(question, file_id, index, key_prefix="sa"):
    answer_key = f"{key_prefix}_answer:{file_id}:{index}"
    feedback_key = f"{key_prefix}_feedback:{file_id}:{index}"

    st.markdown(f"**Question {index}**")
    st.write(question.get("question", ""))

    student_answer = st.text_area(
        "Your answer",
        key=answer_key,
        height=100,
    )

    if st.button("Submit answer", key=f"{key_prefix}_submit:{file_id}:{index}"):
        if not student_answer.strip():
            st.warning("Write an answer before submitting.")
        else:
            prompt = create_short_answer_grade_prompt(
                question.get("question", ""),
                question.get("answer", ""),
                student_answer,
            )

            with st.spinner("Checking answer..."):
                grade_response = ask_gemini(prompt)

            if grade_response:
                try:
                    st.session_state[feedback_key] = (
                        extract_json_from_text(grade_response)
                    )
                except Exception:
                    st.session_state[feedback_key] = {
                        "is_correct": False,
                        "feedback": grade_response,
                    }

    feedback = st.session_state.get(feedback_key)

    if feedback:
        if feedback.get("is_correct"):
            st.success("Correct.")
        else:
            st.error("Not quite.")

        if feedback.get("feedback"):
            st.write(feedback["feedback"])

        st.markdown(f"**Answer:** {question.get('answer', '')}")

        explanation = question.get("explanation")

        if explanation:
            st.write(explanation)


def render_multiple_choice_quiz(quiz_data, file_id):
    questions = quiz_data.get("questions", [])

    if not questions:
        st.warning("The quiz did not include any questions.")
        return

    for index, question in enumerate(questions, start=1):
        with st.container(border=True):
            render_multiple_choice_question(question, file_id, index)


def render_short_answer_quiz(quiz_data, file_id):
    questions = quiz_data.get("questions", [])

    if not questions:
        st.warning("The quiz did not include any questions.")
        return

    for index, question in enumerate(questions, start=1):
        with st.container(border=True):
            render_short_answer_question(question, file_id, index)


def render_mixed_quiz(quiz_data, file_id):
    questions = quiz_data.get("questions", [])

    if not questions:
        st.warning("The quiz did not include any questions.")
        return

    for index, question in enumerate(questions, start=1):
        question_type = question.get("type")

        with st.container(border=True):
            if question_type == "multiple_choice":
                render_multiple_choice_question(
                    question,
                    file_id,
                    index,
                    "mix_mc",
                )
            elif question_type == "short_answer":
                render_short_answer_question(
                    question,
                    file_id,
                    index,
                    "mix_sa",
                )
            else:
                st.warning("This question type could not be displayed.")


def render_flashcard_face(label, text):
    safe_label = html.escape(label)
    safe_text = html.escape(text)

    st.markdown(
        f"""
<div style="
    min-height: 230px;
    border: 1px solid rgba(49, 51, 63, 0.2);
    border-radius: 12px;
    padding: 28px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    background: rgba(250, 250, 250, 0.7);
">
    <div style="
        font-size: 0.8rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(49, 51, 63, 0.65);
        margin-bottom: 18px;
    ">{safe_label}</div>
    <div style="
        font-size: 1.45rem;
        line-height: 1.45;
        font-weight: 600;
        color: rgb(49, 51, 63);
    ">{safe_text}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_flashcards(flashcards_data, file_id):
    flashcards = flashcards_data.get("flashcards", [])

    if not flashcards:
        st.warning("The flashcard response did not include any cards.")
        return

    index_key = f"flashcard_index:{file_id}"
    flipped_key = f"flashcard_flipped:{file_id}"

    if index_key not in st.session_state:
        st.session_state[index_key] = 0

    if flipped_key not in st.session_state:
        st.session_state[flipped_key] = False

    current_index = min(st.session_state[index_key], len(flashcards) - 1)
    st.session_state[index_key] = current_index
    flashcard = flashcards[current_index]
    is_flipped = st.session_state[flipped_key]

    left_spacer, card_column, right_spacer = st.columns([1, 2, 1])

    with card_column:
        st.caption(f"Card {current_index + 1} of {len(flashcards)}")

        if is_flipped:
            render_flashcard_face("Back", flashcard.get("back", ""))
        else:
            render_flashcard_face("Front", flashcard.get("front", ""))

        flip_left, flip_center, flip_right = st.columns([2, 1, 2])

        with flip_center:
            if st.button("Flip card", use_container_width=True):
                st.session_state[flipped_key] = not is_flipped
                st.rerun()

        previous_column, progress_column, next_column = st.columns([1, 2, 1])

        with previous_column:
            if st.button(
                "← Previous",
                disabled=current_index == 0,
                use_container_width=True,
            ):
                st.session_state[index_key] = current_index - 1
                st.session_state[flipped_key] = False
                st.rerun()

        with progress_column:
            progress_value = (current_index + 1) / len(flashcards)
            st.progress(progress_value)

        with next_column:
            if st.button(
                "Next →",
                disabled=current_index == len(flashcards) - 1,
                use_container_width=True,
            ):
                st.session_state[index_key] = current_index + 1
                st.session_state[flipped_key] = False
                st.rerun()


def clear_multiple_choice_state(file_id):
    for index in range(1, 11):
        st.session_state.pop(f"mc_submitted:{file_id}:{index}", None)
        st.session_state.pop(f"mc_selected:{file_id}:{index}", None)
        st.session_state.pop(f"mix_mc_submitted:{file_id}:{index}", None)
        st.session_state.pop(f"mix_mc_selected:{file_id}:{index}", None)


def clear_short_answer_state(file_id):
    for index in range(1, 11):
        st.session_state.pop(f"sa_answer:{file_id}:{index}", None)
        st.session_state.pop(f"sa_feedback:{file_id}:{index}", None)
        st.session_state.pop(f"mix_sa_answer:{file_id}:{index}", None)
        st.session_state.pop(f"mix_sa_feedback:{file_id}:{index}", None)


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
saved_study_notes = None

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
    saved_study_notes = saved_document["study_notes"]
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

show_study_notes(
    notes_text,
    file_id,
    current_user,
    get_current_saved_document_id(file_id),
    saved_study_notes,
)


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

    quiz_state_key = f"quiz:{file_id}"

    if st.button("Generate Quiz"):
        clear_multiple_choice_state(file_id)
        clear_short_answer_state(file_id)

        if quiz_type == "Multiple choice":
            prompt = create_multiple_choice_prompt(notes_text, num_questions)
        elif quiz_type == "Short answer":
            prompt = create_short_answer_prompt(notes_text, num_questions)
        elif quiz_type == "Mixed":
            prompt = create_mixed_quiz_prompt(notes_text, num_questions)
        else:
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
            if quiz_type in {"Multiple choice", "Short answer", "Mixed"}:
                try:
                    quiz_data = extract_json_from_text(quiz)
                    st.session_state[quiz_state_key] = {
                        "type": quiz_type,
                        "content": quiz_data,
                    }
                    quiz_to_save = json.dumps(quiz_data)
                except Exception as error:
                    st.error("The quiz could not be formatted.")
                    st.write(error)
                    st.markdown(quiz)
                    st.session_state[quiz_state_key] = {
                        "type": "Markdown",
                        "content": quiz,
                    }
                    quiz_to_save = quiz
            else:
                st.session_state[quiz_state_key] = {
                    "type": quiz_type,
                    "content": quiz,
                }
                quiz_to_save = quiz

            document_id = get_current_saved_document_id(file_id)

            if document_id:
                try:
                    save_quiz_to_supabase(
                        current_user,
                        document_id,
                        quiz_type,
                        quiz_to_save,
                    )
                except Exception as error:
                    st.warning("The quiz was generated, but could not be saved.")
                    st.write(error)
            elif current_user:
                st.caption("Save this document first to save generated quizzes.")

    active_quiz = st.session_state.get(quiz_state_key)

    if active_quiz:
        if active_quiz["type"] == "Multiple choice":
            render_multiple_choice_quiz(active_quiz["content"], file_id)
            quiz_pdf = create_quiz_pdf(active_quiz["type"], active_quiz["content"])
        elif active_quiz["type"] == "Short answer":
            render_short_answer_quiz(active_quiz["content"], file_id)
            quiz_pdf = create_quiz_pdf(active_quiz["type"], active_quiz["content"])
        elif active_quiz["type"] == "Mixed":
            render_mixed_quiz(active_quiz["content"], file_id)
            quiz_pdf = create_quiz_pdf(active_quiz["type"], active_quiz["content"])
        else:
            st.markdown(active_quiz["content"])
            quiz_pdf = create_text_pdf("Quiz", active_quiz["content"])

        st.download_button(
            "Download quiz PDF",
            data=quiz_pdf,
            file_name="quiz.pdf",
            mime="application/pdf",
        )


with tab3:
    st.subheader("Generate flashcards")

    num_cards = st.slider(
        "Number of flashcards",
        min_value=5,
        max_value=20,
        value=10,
    )

    flashcards_state_key = f"flashcards:{file_id}"

    if st.button("Generate Flashcards"):
        st.session_state.pop(f"flashcard_index:{file_id}", None)
        st.session_state.pop(f"flashcard_flipped:{file_id}", None)
        prompt = create_flashcards_prompt(notes_text, num_cards)

        with st.spinner("Creating flashcards..."):
            flashcards = ask_gemini(prompt)

        if flashcards:
            try:
                flashcards_data = extract_json_from_text(flashcards)
                st.session_state[flashcards_state_key] = {
                    "type": "cards",
                    "content": flashcards_data,
                }
                flashcards_to_save = json.dumps(flashcards_data)
            except Exception as error:
                st.error("The flashcards could not be formatted.")
                st.write(error)
                st.session_state[flashcards_state_key] = {
                    "type": "Markdown",
                    "content": flashcards,
                }
                flashcards_to_save = flashcards

            document_id = get_current_saved_document_id(file_id)

            if document_id:
                try:
                    save_flashcards_to_supabase(
                        current_user,
                        document_id,
                        flashcards_to_save,
                    )
                except Exception as error:
                    st.warning(
                        "The flashcards were generated, but could not be saved."
                    )
                    st.write(error)
            elif current_user:
                st.caption(
                    "Save this document first to save generated flashcards."
                )

    active_flashcards = st.session_state.get(flashcards_state_key)

    if active_flashcards:
        if active_flashcards["type"] == "cards":
            render_flashcards(active_flashcards["content"], file_id)
            flashcards_pdf = create_flashcards_pdf(active_flashcards["content"])
        else:
            st.markdown(active_flashcards["content"])
            flashcards_pdf = create_text_pdf(
                "Flashcards",
                active_flashcards["content"],
            )

        st.download_button(
            "Download flashcards PDF",
            data=flashcards_pdf,
            file_name="flashcards.pdf",
            mime="application/pdf",
        )
