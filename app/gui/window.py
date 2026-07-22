from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from app.config import (
    WEIGHT_NAMES,
    AppConfig,
    ConfigError,
    GalleryConfig,
    load_config,
    parse_config,
    save_config,
)
from app.events import PipelineEvent
from app.gui import GuiUnavailableError
from app.gui.services import (
    CandidateReport,
    GuiInputError,
    find_recent_reports,
    load_candidate_report,
    open_local_file,
    parse_gallery_input,
)
from app.gui.tasks import BackgroundTaskRunner, TaskCompleted
from app.pipeline import PipelineResult, run_pipeline
from app.scripting import ScriptPipelineResult, run_script_pipeline


class ShortsGui:
    def __init__(self, root: tk.Tk, config_path: Path) -> None:
        self.root = root
        self.config_path = config_path
        self.config = load_config(config_path)
        self.galleries: list[GalleryConfig] = []
        self.runner = BackgroundTaskRunner()
        self.recent_reports: tuple[CandidateReport, ...] = ()
        self.current_report: CandidateReport | None = None
        self.candidate_vars: dict[int, tk.BooleanVar] = {}
        self.result_path: Path | None = None
        self.advanced_visible = False

        root.title("Short Daebak · 후보 및 대본 제작")
        root.geometry("1160x840")
        root.minsize(960, 700)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._create_variables()
        self._build_window()
        self._apply_config(self.config)
        self._refresh_recent_reports()
        self.root.after(100, self._poll_events)

    def _create_variables(self) -> None:
        self.config_path_var = tk.StringVar()
        self.pages_var = tk.StringVar()
        self.prefilter_count_var = tk.StringVar()
        self.final_count_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.request_interval_var = tk.StringVar()
        self.http_timeout_var = tk.StringVar()
        self.retries_var = tk.StringVar()
        self.min_body_var = tk.StringVar()
        self.keywords_var = tk.StringVar()
        self.dedupe_days_var = tk.StringVar()
        self.user_agent_var = tk.StringVar()
        self.codex_enabled_var = tk.BooleanVar()
        self.codex_executable_var = tk.StringVar()
        self.codex_timeout_var = tk.StringVar()
        self.weight_vars = {name: tk.StringVar() for name in WEIGHT_NAMES}
        self.report_choice_var = tk.StringVar()
        self.status_var = tk.StringVar(value="준비됨")

    def _build_window(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)
        notebook = ttk.Notebook(container)
        notebook.pack(fill="both", expand=True)
        self.candidate_tab = ttk.Frame(notebook, padding=12)
        self.script_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.candidate_tab, text="후보 생성")
        notebook.add(self.script_tab, text="대본 생성")
        self._build_candidate_tab()
        self._build_script_tab()
        self._build_status_panel(container)

    def _build_candidate_tab(self) -> None:
        tab = self.candidate_tab
        tab.columnconfigure(0, weight=1)
        path_frame = ttk.LabelFrame(tab, text="설정 파일", padding=8)
        path_frame.grid(row=0, column=0, sticky="ew")
        path_frame.columnconfigure(0, weight=1)
        ttk.Label(path_frame, textvariable=self.config_path_var).grid(row=0, column=0, sticky="w")
        ttk.Button(path_frame, text="다른 설정 열기", command=self._choose_config).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(path_frame, text="설정 저장", command=self._save_from_button).grid(
            row=0, column=2, padx=(8, 0)
        )

        gallery_frame = ttk.LabelFrame(tab, text="갤러리", padding=8)
        gallery_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        gallery_frame.columnconfigure(0, weight=1)
        self.gallery_tree = ttk.Treeview(
            gallery_frame,
            columns=("name", "id", "type"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        self.gallery_tree.heading("name", text="표시 이름")
        self.gallery_tree.heading("id", text="갤러리 ID")
        self.gallery_tree.heading("type", text="유형")
        self.gallery_tree.column("name", width=260)
        self.gallery_tree.column("id", width=260)
        self.gallery_tree.column("type", width=100, anchor="center")
        self.gallery_tree.grid(row=0, column=0, sticky="nsew")
        buttons = ttk.Frame(gallery_frame)
        buttons.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ttk.Button(buttons, text="추가", command=self._add_gallery).pack(fill="x")
        ttk.Button(buttons, text="수정", command=self._edit_gallery).pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="삭제", command=self._delete_gallery).pack(fill="x", pady=(6, 0))

        basic = ttk.LabelFrame(tab, text="기본 실행 설정", padding=10)
        basic.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        for column in (1, 3):
            basic.columnconfigure(column, weight=1)
        self._entry_row(basic, 0, 0, "갤러리당 페이지", self.pages_var)
        self._entry_row(basic, 0, 2, "1차 후보 수", self.prefilter_count_var)
        self._entry_row(basic, 1, 0, "최종 후보 수", self.final_count_var)
        ttk.Label(basic, text="출력 폴더").grid(row=1, column=2, sticky="e", padx=(12, 6))
        ttk.Entry(basic, textvariable=self.output_var).grid(row=1, column=3, sticky="ew")
        ttk.Button(basic, text="찾기", command=self._choose_output).grid(
            row=1, column=4, padx=(6, 0)
        )

        advanced_toggle = ttk.Button(tab, text="고급 설정 펼치", command=self._toggle_advanced)
        advanced_toggle.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.advanced_toggle = advanced_toggle
        self.advanced_frame = ttk.LabelFrame(tab, text="고급 설정", padding=10)
        self.advanced_frame.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.advanced_frame.grid_remove()
        self._build_advanced_fields(self.advanced_frame)

        self.run_candidate_button = ttk.Button(
            tab, text="설정 저장 후 후보 생성 실행", command=self._run_candidates
        )
        self.run_candidate_button.grid(row=5, column=0, sticky="e", pady=(12, 0))

    def _build_advanced_fields(self, frame: ttk.LabelFrame) -> None:
        for column in (1, 3):
            frame.columnconfigure(column, weight=1)
        fields = (
            ("요청 간격(초)", self.request_interval_var),
            ("HTTP 타임아웃(초)", self.http_timeout_var),
            ("재시도", self.retries_var),
            ("최소 본문 길이", self.min_body_var),
            ("중복 이력 일수", self.dedupe_days_var),
            ("Codex 타임아웃(초)", self.codex_timeout_var),
        )
        for index, (label, variable) in enumerate(fields):
            row, pair = divmod(index, 2)
            self._entry_row(frame, row, pair * 2, label, variable)
        ttk.Label(frame, text="제외 키워드(쉼표 구분)").grid(
            row=3, column=0, sticky="e", padx=(0, 6), pady=3
        )
        ttk.Entry(frame, textvariable=self.keywords_var).grid(
            row=3, column=1, columnspan=3, sticky="ew", pady=3
        )
        ttk.Label(frame, text="User-Agent").grid(row=4, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Entry(frame, textvariable=self.user_agent_var).grid(
            row=4, column=1, columnspan=3, sticky="ew", pady=3
        )
        ttk.Checkbutton(frame, text="Codex 최종 평가 사용", variable=self.codex_enabled_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=3
        )
        ttk.Label(frame, text="Codex 실행 파일").grid(
            row=5, column=2, sticky="e", padx=(12, 6), pady=3
        )
        ttk.Entry(frame, textvariable=self.codex_executable_var).grid(
            row=5, column=3, sticky="ew", pady=3
        )

        weights = ttk.LabelFrame(frame, text="필터 가중치", padding=8)
        weights.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        for column in (1, 3, 5):
            weights.columnconfigure(column, weight=1)
        labels = {
            "recency": "최신성",
            "recommendations": "추천",
            "comments": "댓글",
            "views": "조회",
            "body_length": "본문 길이",
            "engagement": "참여율",
        }
        for index, name in enumerate(WEIGHT_NAMES):
            row, pair = divmod(index, 3)
            ttk.Label(weights, text=labels[name]).grid(
                row=row, column=pair * 2, sticky="e", padx=(8, 4), pady=2
            )
            ttk.Entry(weights, textvariable=self.weight_vars[name], width=8).grid(
                row=row, column=pair * 2 + 1, sticky="ew", pady=2
            )
        ttk.Label(frame, text="안전 설정: sandbox=read-only · ephemeral=true").grid(
            row=7, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )

    def _build_script_tab(self) -> None:
        tab = self.script_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        selector = ttk.LabelFrame(tab, text="후보 보고서", padding=8)
        selector.grid(row=0, column=0, sticky="ew")
        selector.columnconfigure(0, weight=1)
        self.report_combo = ttk.Combobox(
            selector, textvariable=self.report_choice_var, state="readonly"
        )
        self.report_combo.grid(row=0, column=0, sticky="ew")
        self.report_combo.bind("<<ComboboxSelected>>", self._select_recent_report)
        ttk.Button(selector, text="새로고침", command=self._refresh_recent_reports).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(selector, text="다른 report.html", command=self._choose_report).grid(
            row=0, column=2, padx=(8, 0)
        )
        self.report_info = ttk.Label(tab, text="후보 보고서를 선택하세요.")
        self.report_info.grid(row=1, column=0, sticky="w", pady=(8, 6))

        candidate_frame = ttk.LabelFrame(tab, text="대본으로 만들 후보", padding=4)
        candidate_frame.grid(row=2, column=0, sticky="nsew")
        candidate_frame.columnconfigure(0, weight=1)
        candidate_frame.rowconfigure(0, weight=1)
        self.candidate_canvas = tk.Canvas(candidate_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            candidate_frame, orient="vertical", command=self.candidate_canvas.yview
        )
        self.candidate_list = ttk.Frame(self.candidate_canvas)
        self.candidate_window = self.candidate_canvas.create_window(
            (0, 0), window=self.candidate_list, anchor="nw"
        )
        self.candidate_canvas.configure(yscrollcommand=scrollbar.set)
        self.candidate_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.candidate_list.bind("<Configure>", self._update_candidate_scrollregion)
        self.candidate_canvas.bind("<Configure>", self._resize_candidate_window)

        controls = ttk.Frame(tab)
        controls.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="전체 선택", command=lambda: self._set_all_candidates(True)).pack(
            side="left"
        )
        ttk.Button(
            controls, text="전체 해제", command=lambda: self._set_all_candidates(False)
        ).pack(side="left", padx=(6, 0))
        self.run_script_button = ttk.Button(
            controls, text="선택 후보 대본 생성", command=self._run_scripts
        )
        self.run_script_button.pack(side="right")

    def _build_status_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="실행 상태", padding=8)
        panel.pack(fill="x", pady=(10, 0))
        top = ttk.Frame(panel)
        top.pack(fill="x")
        ttk.Label(top, textvariable=self.status_var).pack(side="left")
        self.open_result_button = ttk.Button(
            top, text="결과 보고서 열기", command=self._open_result, state="disabled"
        )
        self.open_result_button.pack(side="right")
        self.progress = ttk.Progressbar(panel, mode="indeterminate")
        self.progress.pack(fill="x", pady=(6, 6))
        self.log_text = tk.Text(panel, height=7, wrap="word", state="disabled")
        self.log_text.pack(fill="x")

    @staticmethod
    def _entry_row(
        parent: ttk.Widget, row: int, column: int, label: str, variable: tk.StringVar
    ) -> None:
        ttk.Label(parent, text=label).grid(
            row=row, column=column, sticky="e", padx=(0 if column == 0 else 12, 6), pady=3
        )
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=column + 1, sticky="ew", pady=3
        )

    def _apply_config(self, config: AppConfig) -> None:
        self.config = config
        self.config_path_var.set(str(self.config_path.resolve()))
        self.galleries = list(config.dcinside.galleries)
        self._refresh_gallery_tree()
        values = (
            (self.pages_var, config.dcinside.pages_per_gallery),
            (self.prefilter_count_var, config.prefilter.candidate_count),
            (self.final_count_var, config.codex.final_candidate_count),
            (self.output_var, config.output.base_directory),
            (self.request_interval_var, config.dcinside.request_interval_seconds),
            (self.http_timeout_var, config.dcinside.timeout_seconds),
            (self.retries_var, config.dcinside.retries),
            (self.min_body_var, config.dcinside.min_body_length),
            (self.dedupe_days_var, config.dcinside.dedupe_history_days),
            (self.user_agent_var, config.dcinside.user_agent),
            (self.codex_executable_var, config.codex.executable),
            (self.codex_timeout_var, config.codex.timeout_seconds),
        )
        for variable, value in values:
            variable.set(f"{value:g}" if isinstance(value, float) else str(value))
        self.keywords_var.set(", ".join(config.dcinside.excluded_keywords))
        self.codex_enabled_var.set(config.codex.enabled)
        for name, variable in self.weight_vars.items():
            variable.set(f"{config.prefilter.weights[name]:g}")

    def _form_config(self) -> AppConfig:
        def integer(variable: tk.StringVar, label: str) -> int:
            try:
                return int(variable.get().strip())
            except ValueError as exc:
                raise GuiInputError(f"{label}은(는) 정수여야 합니다.") from exc

        def number(variable: tk.StringVar, label: str) -> float:
            try:
                return float(variable.get().strip())
            except ValueError as exc:
                raise GuiInputError(f"{label}은(는) 숫자여야 합니다.") from exc

        mapping: dict[str, Any] = {
            "dcinside": {
                "galleries": [
                    {"id": item.id, "name": item.name, "type": item.type} for item in self.galleries
                ],
                "pages_per_gallery": integer(self.pages_var, "페이지 수"),
                "request_interval_seconds": number(self.request_interval_var, "요청 간격"),
                "timeout_seconds": number(self.http_timeout_var, "HTTP 타임아웃"),
                "retries": integer(self.retries_var, "재시도"),
                "min_body_length": integer(self.min_body_var, "최소 본문 길이"),
                "excluded_keywords": [
                    item.strip() for item in self.keywords_var.get().split(",") if item.strip()
                ],
                "dedupe_history_days": integer(self.dedupe_days_var, "중복 이력 일수"),
                "user_agent": self.user_agent_var.get().strip(),
            },
            "prefilter": {
                "candidate_count": integer(self.prefilter_count_var, "1차 후보 수"),
                "weights": {
                    name: number(variable, f"{name} 가중치")
                    for name, variable in self.weight_vars.items()
                },
            },
            "codex": {
                "enabled": self.codex_enabled_var.get(),
                "executable": self.codex_executable_var.get().strip(),
                "timeout_seconds": number(self.codex_timeout_var, "Codex 타임아웃"),
                "final_candidate_count": integer(self.final_count_var, "최종 후보 수"),
                "sandbox": "read-only",
                "ephemeral": True,
            },
            "output": {"base_directory": self.output_var.get().strip()},
        }
        try:
            return parse_config(mapping)
        except ConfigError as exc:
            raise GuiInputError(str(exc)) from exc

    def _save_form(self, *, notify: bool) -> AppConfig:
        config = self._form_config()
        save_config(self.config_path, config)
        self.config = config
        if notify:
            self.status_var.set(f"설정을 저장했습니다: {self.config_path}")
        return config

    def _save_from_button(self) -> None:
        try:
            self._save_form(notify=True)
            self._refresh_recent_reports()
        except (GuiInputError, OSError) as exc:
            messagebox.showerror("설정 저장 오류", str(exc), parent=self.root)

    def _choose_config(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="설정 파일 선택",
            filetypes=(("YAML 설정", "*.yaml *.yml"), ("모든 파일", "*.*")),
        )
        if not path:
            return
        try:
            config = load_config(path)
        except ConfigError as exc:
            messagebox.showerror("설정 오류", str(exc), parent=self.root)
            return
        self.config_path = Path(path)
        self._apply_config(config)
        self._refresh_recent_reports()

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(parent=self.root, title="출력 폴더 선택")
        if path:
            self.output_var.set(path)

    def _toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_frame.grid()
            self.advanced_toggle.configure(text="고급 설정 접기")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_toggle.configure(text="고급 설정 펼치")

    def _refresh_gallery_tree(self) -> None:
        self.gallery_tree.delete(*self.gallery_tree.get_children())
        for index, gallery in enumerate(self.galleries):
            self.gallery_tree.insert(
                "", "end", iid=str(index), values=(gallery.name, gallery.id, gallery.type)
            )

    def _add_gallery(self) -> None:
        self._gallery_dialog(None)

    def _edit_gallery(self) -> None:
        selected = self.gallery_tree.selection()
        if not selected:
            messagebox.showinfo("갤러리 수정", "수정할 갤러리를 선택하세요.", parent=self.root)
            return
        self._gallery_dialog(int(selected[0]))

    def _delete_gallery(self) -> None:
        selected = self.gallery_tree.selection()
        if not selected:
            return
        del self.galleries[int(selected[0])]
        self._refresh_gallery_tree()

    def _gallery_dialog(self, index: int | None) -> None:
        existing = self.galleries[index] if index is not None else None
        dialog = tk.Toplevel(self.root)
        dialog.title("갤러리 수정" if existing else "갤러리 추가")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        input_var = tk.StringVar(value=existing.id if existing else "")
        name_var = tk.StringVar(value=existing.name if existing else "")
        type_var = tk.StringVar(value=existing.type if existing else "major")
        ttk.Label(frame, text="갤러리 URL 또는 ID").grid(row=0, column=0, sticky="e", pady=4)
        ttk.Entry(frame, textvariable=input_var, width=48).grid(
            row=0, column=1, sticky="ew", padx=(8, 0), pady=4
        )
        ttk.Label(frame, text="표시 이름").grid(row=1, column=0, sticky="e", pady=4)
        ttk.Entry(frame, textvariable=name_var).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=4
        )
        ttk.Label(frame, text="유형").grid(row=2, column=0, sticky="e", pady=4)
        ttk.Combobox(
            frame, textvariable=type_var, values=("major", "minor"), state="readonly"
        ).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)
        frame.columnconfigure(1, weight=1)

        def save() -> None:
            try:
                gallery_id, gallery_type = parse_gallery_input(input_var.get(), type_var.get())
                name = name_var.get().strip()
                if not name:
                    raise GuiInputError("표시 이름을 입력하세요.")
                gallery = GalleryConfig(gallery_id, name, gallery_type)
                if index is None:
                    self.galleries.append(gallery)
                else:
                    self.galleries[index] = gallery
                self._refresh_gallery_tree()
                dialog.destroy()
            except GuiInputError as exc:
                messagebox.showerror("갤러리 오류", str(exc), parent=dialog)

        actions = ttk.Frame(frame)
        actions.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="취소", command=dialog.destroy).pack(side="left")
        ttk.Button(actions, text="저장", command=save).pack(side="left", padx=(6, 0))

    def _refresh_recent_reports(self) -> None:
        try:
            base = self._form_config().output.base_directory
        except GuiInputError:
            base = self.config.output.base_directory
        self.recent_reports = find_recent_reports(base)
        values = [report.display_name for report in self.recent_reports]
        self.report_combo.configure(values=values)
        self.report_choice_var.set(values[0] if values else "")
        if values:
            self._load_report(self.recent_reports[0])
        else:
            self.current_report = None
            self.report_info.configure(text="성공한 후보 보고서가 없습니다.")
            self._render_candidates(())

    def _select_recent_report(self, _event: tk.Event[Any]) -> None:
        index = self.report_combo.current()
        if 0 <= index < len(self.recent_reports):
            self._load_report(self.recent_reports[index])

    def _choose_report(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="후보 report.html 선택",
            filetypes=(("HTML 보고서", "*.html"), ("모든 파일", "*.*")),
        )
        if not path:
            return
        try:
            report = load_candidate_report(path)
        except GuiInputError as exc:
            messagebox.showerror("보고서 오류", str(exc), parent=self.root)
            return
        self.report_choice_var.set(str(report.report_path))
        self._load_report(report)

    def _load_report(self, report: CandidateReport) -> None:
        self.current_report = report
        self.report_info.configure(text=f"{report.display_name}\n{report.report_path}")
        self._render_candidates(report.candidates)

    def _render_candidates(self, candidates: tuple[Any, ...]) -> None:
        for child in self.candidate_list.winfo_children():
            child.destroy()
        self.candidate_vars.clear()
        for candidate in candidates:
            variable = tk.BooleanVar(value=False)
            self.candidate_vars[candidate.rank] = variable
            card = ttk.Frame(self.candidate_list, padding=10, relief="solid", borderwidth=1)
            card.pack(fill="x", padx=4, pady=4)
            header = ttk.Frame(card)
            header.pack(fill="x")
            ttk.Checkbutton(
                header,
                text=f"{candidate.rank}위 · {candidate.title}",
                variable=variable,
            ).pack(side="left", fill="x", expand=True)
            color = {"low": "#006d77", "medium": "#8a4b00", "high": "#a11b26"}[candidate.risk_level]
            tk.Label(
                header,
                text=f"위험도 {candidate.risk_level}",
                foreground=color,
                font=("Segoe UI", 9, "bold"),
            ).pack(side="right")
            ttk.Label(card, text=candidate.summary, wraplength=900).pack(
                fill="x", anchor="w", pady=(5, 0)
            )
            ttk.Label(card, text=f"추천 이유: {candidate.reason}", wraplength=900).pack(
                fill="x", anchor="w", pady=(3, 0)
            )
            ttk.Label(card, text=f"훅: {candidate.hook}", wraplength=900).pack(
                fill="x", anchor="w", pady=(3, 0)
            )
            scores = (
                f"종합 {candidate.total_score} · 재미 {candidate.fun_score} · "
                f"반전 {candidate.twist_score} · 명확성 {candidate.clarity_score} · "
                f"쇼츠 {candidate.shorts_fit_score}"
            )
            ttk.Label(card, text=scores).pack(fill="x", anchor="w", pady=(3, 0))
            if candidate.risks:
                ttk.Label(card, text="위험: " + " / ".join(candidate.risks), wraplength=900).pack(
                    fill="x", anchor="w", pady=(3, 0)
                )
            ttk.Label(card, text=f"검토: {candidate.review_notes}", wraplength=900).pack(
                side="left", fill="x", expand=True, anchor="w", pady=(3, 0)
            )
            ttk.Button(
                card,
                text="원문 열기",
                command=lambda url=candidate.url: self._open_path(url),
            ).pack(side="right")

    def _update_candidate_scrollregion(self, _event: tk.Event[Any]) -> None:
        self.candidate_canvas.configure(scrollregion=self.candidate_canvas.bbox("all"))

    def _resize_candidate_window(self, event: tk.Event[Any]) -> None:
        self.candidate_canvas.itemconfigure(self.candidate_window, width=event.width)

    def _set_all_candidates(self, selected: bool) -> None:
        for variable in self.candidate_vars.values():
            variable.set(selected)

    def _run_candidates(self) -> None:
        try:
            config = self._save_form(notify=False)
        except (GuiInputError, OSError) as exc:
            messagebox.showerror("실행 설정 오류", str(exc), parent=self.root)
            return
        self._start_task(
            "candidate",
            lambda callback: run_pipeline(config, event_callback=callback),
            "후보를 수집하고 평가하는 중입니다.",
        )

    def _run_scripts(self) -> None:
        if self.current_report is None:
            messagebox.showinfo("대본 생성", "후보 보고서를 먼저 선택하세요.", parent=self.root)
            return
        ranks = tuple(rank for rank, variable in self.candidate_vars.items() if variable.get())
        if not ranks:
            messagebox.showinfo("대본 생성", "하나 이상의 후보를 선택하세요.", parent=self.root)
            return
        high = [
            candidate.rank
            for candidate in self.current_report.candidates
            if candidate.rank in ranks and candidate.risk_level == "high"
        ]
        if high and not messagebox.askyesno(
            "고위험 후보 확인",
            f"고위험 후보 {', '.join(map(str, high))}위를 포함해 대본을 생성할까요?",
            parent=self.root,
        ):
            return
        try:
            config = self._save_form(notify=False)
        except (GuiInputError, OSError) as exc:
            messagebox.showerror("실행 설정 오류", str(exc), parent=self.root)
            return
        run_directory = self.current_report.run_directory
        self._start_task(
            "script",
            lambda callback: run_script_pipeline(
                config, run_directory, ranks, event_callback=callback
            ),
            "선택한 후보의 대본을 생성하는 중입니다.",
        )

    def _start_task(self, name: str, work: Any, status: str) -> None:
        if not self.runner.start(name, work):
            messagebox.showinfo("실행 중", "다른 작업이 끝날 때까지 기다리세요.", parent=self.root)
            return
        self._set_running(True)
        self.status_var.set(status)
        self.result_path = None
        self.open_result_button.configure(state="disabled")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self._clear_log()

    def _poll_events(self) -> None:
        for event in self.runner.drain():
            if isinstance(event, PipelineEvent):
                self._handle_pipeline_event(event)
            elif isinstance(event, TaskCompleted):
                self._handle_task_completed(event)
        self.root.after(100, self._poll_events)

    def _handle_pipeline_event(self, event: PipelineEvent) -> None:
        self._append_log(event.message)
        self.status_var.set(event.message)
        if event.progress_percent is not None:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=event.progress_percent)

    def _handle_task_completed(self, event: TaskCompleted) -> None:
        self._set_running(False)
        self.progress.stop()
        if event.error is not None:
            self.status_var.set(f"실행 오류: {event.error}")
            messagebox.showerror("실행 오류", str(event.error), parent=self.root)
            return
        result = event.result
        if isinstance(result, PipelineResult):
            report_path = result.output_directory / "report.html"
        elif isinstance(result, ScriptPipelineResult):
            report_path = result.output_directory / "script_report.html"
        else:
            self.status_var.set("알 수 없는 실행 결과입니다.")
            return
        self.status_var.set(f"완료: {result.status} · {result.output_directory}")
        if report_path.is_file():
            self.result_path = report_path
            self.open_result_button.configure(state="normal")
        if event.name == "candidate" and result.status == "success":
            self._refresh_recent_reports()

    def _set_running(self, running: bool) -> None:
        for tab in (self.candidate_tab, self.script_tab):
            self._set_interactive_state(tab, running)

    def _set_interactive_state(self, parent: tk.Misc, running: bool) -> None:
        for widget in parent.winfo_children():
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="disabled" if running else "readonly")
            elif isinstance(
                widget,
                (ttk.Button, ttk.Checkbutton, ttk.Entry, ttk.Treeview),
            ):
                widget.state(("disabled",) if running else ("!disabled",))
            self._set_interactive_state(widget, running)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _open_result(self) -> None:
        if self.result_path is not None:
            self._open_path(self.result_path)

    def _open_path(self, path: str | Path) -> None:
        try:
            if isinstance(path, str) and path.startswith(("http://", "https://")):
                import webbrowser

                if not webbrowser.open(path):
                    raise GuiInputError("기본 브라우저를 시작하지 못했습니다.")
            else:
                open_local_file(path)
        except GuiInputError as exc:
            messagebox.showerror("파일 열기 오류", str(exc), parent=self.root)

    def _on_close(self) -> None:
        if self.runner.busy:
            messagebox.showwarning(
                "실행 중",
                "현재 작업이 끝난 뒤 창을 닫아주세요.",
                parent=self.root,
            )
            return
        self.root.destroy()


def launch_gui(config_path: Path) -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise GuiUnavailableError(f"GUI 창을 시작할 수 없습니다: {exc}") from exc
    try:
        ShortsGui(root, config_path)
    except Exception:
        root.destroy()
        raise
    root.mainloop()
    return 0
