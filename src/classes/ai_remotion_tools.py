"""
Remotion-related tools for the AI agent: list templates, generate props from
user prompt via LLM, render compositions, and add clips to timeline.

Heavy work (LLM call + subprocess renders) runs in a QThread worker;
only file-import / timeline-add runs on the Qt main thread.
"""

import json
import os
import tempfile

from classes.logger import log

try:
    from PyQt5.QtCore import QObject, QThread, pyqtSignal, QEventLoop
except ImportError:
    QObject = object
    QThread = None
    pyqtSignal = None
    QEventLoop = None


# ---------------------------------------------------------------------------
#  Props generation (runs in worker thread — no Qt dependency)
# ---------------------------------------------------------------------------

def _generate_props_from_prompt(prompt, template_meta, model_id=None, repo_data=None):
    """
    Use the LLM to turn a natural-language prompt into JSON props for each
    composition. Optionally enhanced with GitHub repository data.

    Returns (dict_mapping_comp_id_to_props, None) or (None, err).
    """
    from classes.ai_llm_registry import get_model, get_default_model_id

    mid = model_id or get_default_model_id()
    llm = get_model(mid) if mid else None
    if not llm:
        return None, "No AI model configured. Set an API key in Preferences > AI."

    comp_descs = []
    for comp in template_meta.get("compositions", []):
        schema = comp.get("props_schema", {})
        comp_descs.append(
            'Composition "%s" (%s):\n%s'
            % (comp["id"], comp.get("description", ""), json.dumps(schema, indent=2))
        )
    all_comps = "\n\n".join(comp_descs)

    # IF GITHUB REPO DATA EXISTS: Use repo-specific prompt
    if repo_data:
        # Get language-based color
        lang = repo_data.get('language', '').lower()
        color_map = {
            'javascript': '#F7DF1E',
            'typescript': '#3178C6',
            'python': '#3776AB',
            'go': '#00ADD8',
            'rust': '#CE422B',
            'java': '#007396',
            'ruby': '#CC342D',
            'c++': '#00599C',
            'c#': '#239120',
            'php': '#777BB4',
            'swift': '#FA7343',
            'kotlin': '#7F52FF',
        }
        accent_color = color_map.get(lang, '#6C63FF')

        # Prepare features for prompt
        features_list = repo_data.get('features', [])[:3]
        if not features_list:
            features_list = ['Open Source', 'Well Documented', 'Community Driven']

        system = f"""You are generating props for a Remotion video based on this GitHub repository:

PROJECT DATA:
- Name: {repo_data.get('name', 'Project')}
- Description: {repo_data.get('description', 'An awesome project')}
- Language: {repo_data.get('language', 'Unknown')}
- Stars: {repo_data.get('stars', 0):,}
- Website: {repo_data.get('website', repo_data.get('github_url', ''))}
- Features: {', '.join(features_list)}

REQUIRED OUTPUT FORMAT (compositions: {', '.join([c['id'] for c in template_meta.get('compositions', [])])}):
{{
  "LaunchIntro": {{
    "productName": "{repo_data.get('name', 'Project')}",
    "tagline": "[Create catchy 3-4 word tagline from description]",
    "accentColor": "{accent_color}",
    "bgColor": "#0a0a1a"
  }},
  "FeatureShowcase": {{
    "productName": "{repo_data.get('name', 'Project')}",
    "features": [
      {{"title": "[Feature 1 from list]", "description": "[Short desc 4-6 words]"}},
      {{"title": "[Feature 2 from list]", "description": "[Short desc 4-6 words]"}},
      {{"title": "[Feature 3 from list]", "description": "[Short desc 4-6 words]"}}
    ],
    "accentColor": "{accent_color}",
    "bgColor": "#0a0a1a"
  }},
  "CallToAction": {{
    "productName": "{repo_data.get('name', 'Project')}",
    "ctaText": "View on GitHub",
    "website": "{repo_data.get('website', repo_data.get('github_url', ''))}",
    "accentColor": "{accent_color}",
    "bgColor": "#0a0a1a"
  }}
}}

INSTRUCTIONS:
1. Use the EXACT productName: {repo_data.get('name', 'Project')}
2. Create tagline from the description (max 4 words)
3. Use the features list provided above
4. Use the EXACT accentColor: {accent_color}
5. Output ONLY valid JSON, no markdown
"""
        log.info("Using GitHub-enhanced prompt for: %s (color: %s)", repo_data.get('name'), accent_color)
    else:
        # Original prompt for non-GitHub requests
        system = f"""You are an expert motion designer. Generate props for this Remotion template:

Template: {template_meta.get("title", "")}
Compositions:
{all_comps}

EXAMPLES:

Input: "Professional product launch for BankPro with security, speed, rewards"
Output:
{{
  "LaunchIntro": {{
    "productName": "BankPro",
    "tagline": "Banking Made Secure",
    "accentColor": "#1E40AF",
    "bgColor": "#0a0a1a"
  }},
  "FeatureShowcase": {{
    "productName": "BankPro",
    "features": [
      {{"title": "Bank-Grade Security", "description": "Your money, protected"}},
      {{"title": "Lightning Fast", "description": "Instant transactions"}},
      {{"title": "Smart Rewards", "description": "Earn while you spend"}}
    ],
    "accentColor": "#1E40AF",
    "bgColor": "#0a0a1a"
  }},
  "CallToAction": {{
    "productName": "BankPro",
    "ctaText": "Open Account Today",
    "website": "bankpro.com",
    "accentColor": "#1E40AF",
    "bgColor": "#0a0a1a"
  }}
}}

RULES:
1. Match colors to the industry: Tech=Blue, Fitness=Orange, Finance=Navy, Luxury=Gold
2. Keep features short: Title 2-3 words, description 5-7 words
3. Make tagline catchy and relevant
4. Use same accentColor across all compositions
5. Output ONLY JSON, no markdown backticks
"""

    log.info("Generating props for prompt: %s", prompt)
    log.debug("System prompt:\n%s", system)

    # Simplify user message if repo data exists (all info already in system prompt)
    user_message = prompt
    if repo_data:
        user_message = f"Generate the video props for {repo_data.get('name', 'this project')} using the data provided above. Output only JSON."
        log.info("Using simplified user message for repo-based generation")

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user_message)])
        text = getattr(response, "content", None) or str(response)
        log.info("LLM raw response: %s", text[:500])
    except Exception as e:
        log.error("LLM props generation failed: %s", e, exc_info=True)
        return None, "Failed to generate props: %s" % e

    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
        log.info("Cleaned JSON (removed markdown): %s", text[:500])

    try:
        props = json.loads(text)
        log.info("Successfully parsed props JSON")

        # Verify props structure
        if repo_data:
            expected_name = repo_data.get('name', '')
            for comp_id, comp_props in props.items():
                if 'productName' in comp_props:
                    actual_name = comp_props['productName']
                    log.info("Composition '%s' productName: %s (expected: %s)",
                            comp_id, actual_name, expected_name)
                    if actual_name in ['My Product', 'My Project']:
                        log.warning("⚠️  LLM used default name instead of repo name!")

        log.info("Final props: %s", json.dumps(props, indent=2))
    except json.JSONDecodeError as e:
        log.error("JSON parse failed: %s\nRaw text:\n%s", e, text)
        return None, "LLM returned invalid JSON: %s\nRaw:\n%s" % (e, text[:500])

    if not isinstance(props, dict):
        return None, "LLM returned non-object JSON."
    return props, None


# ---------------------------------------------------------------------------
#  QThread worker — props generation + Remotion render (off the main thread)
# ---------------------------------------------------------------------------

class _RemotionWorkerThread(QThread if QThread else object):
    """Heavy work in run(), signal result when done."""
    if pyqtSignal is not None:
        finished_signal = pyqtSignal(str, str)  # json_paths_list, error

    def __init__(self, prompt, template_meta, model_id):
        if QThread is not None:
            super().__init__()
        self._prompt = prompt
        self._template_meta = template_meta
        self._model_id = model_id

    def run(self):
        """Executed in the worker thread."""
        try:
            paths_json, error = self._do_work()
            if pyqtSignal is not None and hasattr(self, "finished_signal"):
                self.finished_signal.emit(paths_json or "[]", error or "")
        except Exception as e:
            log.error("_RemotionWorkerThread.run: %s", e, exc_info=True)
            if pyqtSignal is not None and hasattr(self, "finished_signal"):
                self.finished_signal.emit("[]", str(e))

    def _do_work(self):
        from classes.remotion_runner import render_all_compositions, get_template_dir

        template_dir_name = self._template_meta.get("template_dir")
        if not template_dir_name:
            return None, "Template has no template_dir."

        template_dir = get_template_dir(template_dir_name)
        if not template_dir:
            return None, "Template directory '%s' not found." % template_dir_name

        compositions = self._template_meta.get("compositions", [])
        if not compositions:
            return None, "Template has no compositions."

        # --- Fetch GitHub repo data if URL detected (worker thread - safe for I/O) ---
        repo_data = None
        if 'github.com' in self._prompt.lower():
            import re
            from classes.github_repo_analyzer import fetch_github_repo_data

            # Extract GitHub URLs from prompt
            github_pattern = r'https?://github\.com/[\w\-]+/[\w\-\.]+'
            github_urls = re.findall(github_pattern, self._prompt, re.IGNORECASE)

            if github_urls:
                log.info("Detected GitHub URL in prompt: %s", github_urls[0])
                repo_data, fetch_err = fetch_github_repo_data(github_urls[0])
                if fetch_err:
                    log.warning("GitHub fetch failed (will continue with prompt-only): %s", fetch_err)
                    repo_data = None
                else:
                    log.info("Successfully fetched GitHub repo: %s (%d stars)",
                            repo_data.get('name'), repo_data.get('stars', 0))

        # --- Generate props via LLM (enhanced with repo_data if available) ---
        per_comp_props, err = _generate_props_from_prompt(
            self._prompt, self._template_meta, self._model_id, repo_data=repo_data
        )
        if err:
            log.error("Props generation error: %s", err)
            return None, err

        log.info("Props generated for compositions: %s", json.dumps(per_comp_props, indent=2))

        # --- Render ---
        output_dir = tempfile.mkdtemp(prefix="flowcut_remotion_")
        log.info("Rendering to: %s", output_dir)
        video_paths, render_err = render_all_compositions(
            template_dir, compositions, per_comp_props or {}, output_dir
        )
        if render_err:
            return None, render_err
        if not video_paths:
            return None, "No videos were rendered."

        return json.dumps(video_paths), None


# ---------------------------------------------------------------------------
#  Main-thread entry point (called by the tool, runs on the Qt main thread)
# ---------------------------------------------------------------------------

def generate_remotion_video_and_add_to_timeline(
    prompt,
    template_id=None,
    add_scenes_as_separate_clips=True,
    model_id=None,
):
    """
    End-to-end: pick template, generate props, render, import, add to timeline.
    Heavy work runs in a QThread; this function uses a QEventLoop to stay
    responsive while waiting.
    """
    if QThread is None or QEventLoop is None:
        return "Error: Remotion video generation requires PyQt5."

    from classes.app import get_app
    from classes.remotion_prompts import load_prompts, get_prompt

    app = get_app()

    # ── Resolve template ────────────────────────────────────────────
    prompts = load_prompts()
    template_meta = None

    if template_id:
        template_meta = get_prompt(template_id)
    if not template_meta and prompts:
        if len(prompts) == 1:
            template_meta = prompts[0]
        else:
            prompt_lower = prompt.lower()
            for p in prompts:
                keywords = (p.get("title", "") + " " + p.get("description", "")).lower()
                if any(w in prompt_lower for w in keywords.split() if len(w) > 3):
                    template_meta = p
                    break
            if not template_meta:
                template_meta = prompts[0]

    if not template_meta:
        return "Error: No Remotion templates found."

    # ── Kick off worker thread ──────────────────────────────────────
    result_holder = [None, None]  # [paths_json, error]
    loop_holder = [None]

    class _DoneReceiver(QObject if QObject is not object else object):
        def on_done(self, paths_json, error):
            result_holder[0] = paths_json
            result_holder[1] = error
            if loop_holder[0]:
                loop_holder[0].quit()

    receiver = _DoneReceiver()
    thread = _RemotionWorkerThread(prompt, template_meta, model_id)
    thread.finished_signal.connect(receiver.on_done)
    loop_holder[0] = QEventLoop(app)

    status_bar = getattr(app.window, "statusBar", None)
    try:
        if status_bar is not None:
            status_bar.showMessage("Rendering Remotion video…", 0)
        thread.start()
        loop_holder[0].exec_()
    finally:
        if status_bar is not None:
            status_bar.clearMessage()

    thread.quit()
    thread.wait(10000)
    try:
        thread.finished_signal.disconnect(receiver.on_done)
    except Exception:
        pass

    # ── Handle result ───────────────────────────────────────────────
    paths_json, error = result_holder[0], result_holder[1]
    if error:
        if "No AI model configured" in error or "api key" in error.lower():
            return ("Error: %s\nPlease configure an AI provider (OpenAI, Anthropic, "
                    "or Ollama) in Preferences > AI." % error)
        return "Error: %s" % error

    try:
        video_paths = json.loads(paths_json) if paths_json else []
    except Exception:
        video_paths = []
    if not video_paths:
        return "Error: No videos were rendered."

    # ── Optionally concatenate ──────────────────────────────────────
    if not add_scenes_as_separate_clips and len(video_paths) > 1:
        try:
            from classes.ai_manim_tools import concatenate_videos_ffmpeg
            combined = os.path.join(os.path.dirname(video_paths[0]), "combined.mp4")
            ok, concat_err = concatenate_videos_ffmpeg(video_paths, combined)
            if ok:
                paths_to_add = [combined]
            else:
                log.warning("Concatenation failed (%s), adding scenes separately", concat_err)
                paths_to_add = video_paths
        except ImportError:
            paths_to_add = video_paths
    else:
        paths_to_add = video_paths

    # ── Import + add to timeline (main thread — fast) ───────────────
    log.info("Adding %d video(s) to project: %s", len(paths_to_add), paths_to_add)
    try:
        app.window.files_model.add_files(paths_to_add)
    except Exception as e:
        log.error("add_files failed: %s", e, exc_info=True)
        return "Error adding files to project: %s" % e

    # Process events to allow file model to update
    if hasattr(app, "processEvents"):
        app.processEvents()

    from classes.query import File
    from classes.ai_openshot_tools import add_clip_to_timeline
    import time

    # Give the file model a moment to index the files
    time.sleep(0.3)

    added = 0
    for path in paths_to_add:
        path_norm = os.path.normpath(path)
        log.info("Looking for file in database: %s", path)

        f = File.get(path=path) or File.get(path=path_norm)
        if not f:
            log.info("File not found by path, searching all files...")
            for candidate in File.filter():
                candidate_path = getattr(candidate, "path", None)
                candidate_abs = getattr(candidate, "absolute_path", None)
                if candidate_abs and callable(candidate_abs):
                    candidate_abs = candidate_abs()
                if candidate_path == path or candidate_abs == path or candidate_abs == path_norm:
                    f = candidate
                    log.info("Found file by iteration: %s (id=%s)", path, f.id)
                    break
        else:
            log.info("Found file: %s (id=%s)", path, f.id)

        if f:
            try:
                add_clip_to_timeline(file_id=str(f.id), position_seconds=None, track=None)
                added += 1
                log.info("Added clip %d to timeline", added)
            except Exception as e:
                log.error("Failed to add clip to timeline: %s", e, exc_info=True)
        else:
            log.warning("Could not find file in database: %s", path)

    log.info("Total clips added to timeline: %d", added)
    template_title = template_meta.get("title", template_meta.get("id", ""))
    scene_word = "scene" if added == 1 else "scenes"
    return (
        "Rendered %d %s from the \"%s\" template and added them to the timeline. "
        "Click each clip to preview or edit individually."
        % (added, scene_word, template_title)
    )


# ---------------------------------------------------------------------------
#  Read-only helper
# ---------------------------------------------------------------------------

def list_remotion_templates():
    """Return a human-readable list of available Remotion templates."""
    from classes.remotion_prompts import load_prompts
    prompts = load_prompts()
    if not prompts:
        return "No Remotion templates are available."
    lines = []
    for p in prompts:
        pid = p.get("id", "")
        title = p.get("title", pid)
        desc = p.get("description", "(no description)")
        comps = p.get("compositions", [])
        comp_ids = ", ".join(c.get("id", "") for c in comps)
        lines.append("- %s (id=%s) -- %s\n  Scenes: %s" % (title, pid, desc, comp_ids))
    return "Available Remotion templates:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
#  LangChain tool wrappers
# ---------------------------------------------------------------------------

def get_remotion_tools_for_langchain():
    """Return a list of LangChain Tool objects for the Remotion agent."""
    from langchain_core.tools import tool

    @tool
    def list_remotion_templates_tool() -> str:
        """List all available Remotion animated video templates with their scenes and descriptions."""
        return list_remotion_templates()

    @tool
    def generate_remotion_video_tool(
        prompt: str,
        template_id: str = "",
        add_scenes_as_separate_clips: bool = True,
    ) -> str:
        """Generate an animated video using a Remotion template and add it to the timeline.
        The AI customizes template props (text, colors, features) based on the prompt.

        Arguments:
          prompt: describe the video (e.g. "Product launch for SuperTask with
                  features: AI-powered, Real-time sync, Cross-platform")
          template_id: optional template id (e.g. "product-launch"). Auto-selected if empty.
          add_scenes_as_separate_clips: True (default) = each scene is a separate timeline clip.
        """
        return generate_remotion_video_and_add_to_timeline(
            prompt=prompt,
            template_id=template_id.strip() if template_id else None,
            add_scenes_as_separate_clips=add_scenes_as_separate_clips,
        )

    return [list_remotion_templates_tool, generate_remotion_video_tool]
