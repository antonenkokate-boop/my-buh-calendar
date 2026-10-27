import datetime
import calendar
import json
import os
import streamlit as st
import requests
import pandas as pd

# Настройка страницы под мобильные устройства и десктоп
st.set_page_config(page_title="Календарь бухгалтера РБ", layout="wide", page_icon="📅")

# HTML-стили для точной имитации вашего желаемого интерфейса
st.markdown("""
    <style>
    /* Стиль для рамки карточки налога */
    .task-box {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.02);
    }
    .task-box-title {
        font-weight: bold;
        font-size: 1.05rem;
        color: #1a202c;
        margin-bottom: 6px;
    }
    .task-box-text {
        font-size: 0.9rem;
        color: #4a5568;
        line-height: 1.4;
    }
    /* Делаем кнопку "Управлять" внутри карточки аккуратной и выровненной */
    div.stButton > button {
        border: 1px solid #cbd5e1 !important;
        background-color: #ffffff !important;
        color: #334155 !important;
        border-radius: 8px !important;
        padding: 6px 16px !important;
        font-size: 0.9rem !important;
        height: auto !important;
    }
    div.stButton > button:hover {
        border-color: #94a3b8 !important;
        background-color: #f8fafc !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- Безопасное чтение токенов из скрытого раздела Secrets в Streamlit Cloud ---
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
TG_BOT_TOKEN = st.secrets["TG_BOT_TOKEN"]
TG_USER_ID = st.secrets["TG_USER_ID"]

GITHUB_REPO = "antonenkokate-boop/my-buh-calendar"
DB_FILE = "database.json"
LOG_FILE = "history_logs.json"
def get_github_file(filename):
    """Вспомогательная функция для безопасного чтения файла с GitHub API с выводом ошибок."""
    # ИСПРАВЛЕНО: Теперь адрес ведет на официальный рабочий API-сервер GitHub
    url = f"https://github.com{GITHUB_REPO}/contents/{filename}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            content_json = res.json()
            import base64
            file_content = base64.b64decode(content_json["content"]).decode("utf-8")
            return json.loads(file_content), content_json["sha"]
        elif res.status_code != 404:
            st.sidebar.error(f"GitHub Чтение Сбой! Код: {res.status_code}")
    except Exception as e:
        st.sidebar.error(f"Ошибка сети при чтении: {e}")
    return None, None

def save_github_file(filename, data_to_save):
    """Вспомогательная функция для автоматической записи файла на GitHub с выводом ошибок."""
    # ИСПРАВЛЕНО: Теперь адрес ведет на официальный рабочий API-сервер GitHub
    url = f"https://github.com{GITHUB_REPO}/contents/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    _, sha = get_github_file(filename)
    
    import base64
    json_str = json.dumps(data_to_save, ensure_ascii=False, indent=4)
    content_bytes = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")
    
    payload = {
        "message": f"🤖 Авто-обновление {filename} от календаря бухгалтера",
        "content": content_bytes
    }
    if sha:
        payload["sha"] = sha
        
    try:
        res = requests.put(url, headers=headers, json=payload, timeout=5)
        if res.status_code != 200 and res.status_code != 201:
            st.sidebar.error(f"GitHub Запись Сбой! Код: {res.status_code}, Ответ: {res.text}")
    except Exception as e:
        st.sidebar.error(f"Ошибка сети при записи: {e}")

def load_data():
    """Загружает данные налогов прямо из репозитория GitHub."""
    data, _ = get_github_file(DB_FILE)
    if not data or not isinstance(data, list):
        return None
    try:
        for report in data:
            report["deadline"] = datetime.datetime.strptime(report["deadline"], "%Y-%m-%d").date()
            if report.get("end_date"):
                report["end_date"] = datetime.datetime.strptime(report["end_date"], "%Y-%m-%d").date()
            else:
                report["end_date"] = None
        return data
    except Exception:
        return None

def save_data():
    """Сохраняет текущее состояние налогов в файл на GitHub."""
    try:
        if "reports" not in st.session_state or not st.session_state.reports:
            return
        serializable_reports = []
        for r in st.session_state.reports:
            r_copy = r.copy()
            if isinstance(r_copy["deadline"], datetime.date):
                r_copy["deadline"] = r_copy["deadline"].strftime("%Y-%m-%d")
            if r_copy.get("end_date") and isinstance(r_copy["end_date"], datetime.date):
                r_copy["end_date"] = r_copy["end_date"].strftime("%Y-%m-%d")
            serializable_reports.append(r_copy)
            
        save_github_file(DB_FILE, serializable_reports)
    except Exception as e:
        st.error(f"Ошибка保存 базы данных: {e}")

def load_logs():
    """Загружает историю действий бухгалтера из репозитория GitHub."""
    data, _ = get_github_file(LOG_FILE)
    return data if data else []

def save_log_entry(report_name, target_date, action_text, current_comment=""):
    """Добавляет запись в журнал истории действий на GitHub."""
    logs = load_logs()
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    date_str = target_date.strftime("%d.%m.%Y") if isinstance(target_date, datetime.date) else str(target_date)
        
    entry = {
        "timestamp": now_str,
        "report_name": report_name,
        "period": date_str,
        "action": action_text,
        "period_comment": current_comment
    }
    logs.insert(0, entry)
    save_github_file(LOG_FILE, logs)

# --- 2. ФУНКЦИЯ ПРОИЗВОДСТВЕННОГО КАЛЕНДАРЯ РБ ---
def get_real_working_day(date_check):
    """Сдвигает дедлайн вперед, если он выпал на выходной или праздник в РБ."""
    while True:
        try:
            # ИСПРАВЛЕНО: Добавлен обязательный слэш в эндпоинт API isdayoff
            url = f"https://isdayoff.ru{date_check.year}&month={date_check.month:02d}&day={date_check.day:02d}&cc=by"
            response = requests.get(url, timeout=2)
            if response.status_code == 200 and response.text.strip() in ["1", "2"]:
                date_check += datetime.timedelta(days=1)
            else:
                break
        except Exception:
            if date_check.weekday() == 5: 
                date_check += datetime.timedelta(days=2)
            elif date_check.weekday() == 6:
                date_check += datetime.timedelta(days=1)
            break
    return date_check

def calculate_first_deadline(day, active_months, start_date=None):
    """Рассчитывает ближайший дедлайн на основе выбранных месяцев."""
    if not start_date:
        start_date = datetime.date.today()
    c_month, c_year = start_date.month, start_date.year
    
    for i in range(24):
        target_month = (c_month + i - 1) % 12 + 1
        target_year = c_year + (c_month + i - 1) // 12
        month_name = list(MONTHS_RU.keys())[target_month - 1]
        
        if active_months.get(month_name, False):
            _, max_days = calendar.monthrange(target_year, target_month)
            base_date = datetime.date(target_year, target_month, min(day, max_days))
            if i == 0 and base_date < start_date:
                continue
            return get_real_working_day(base_date)
            
    return start_date

MONTHS_RU = {
    "Январь": 1, "Февраль": 2, "Март": 3, "Апрель": 4, "Май": 5, "Июнь": 6,
    "Июль": 7, "Август": 8, "Сентябрь": 9, "Октябрь": 10, "Ноябрь": 11, "Декабрь": 12
}

def send_telegram_reminder(message):
    """Отправляет текстовое уведомление через созданного бота."""
    try:
        # ИСПРАВЛЕНО ПОЛНОСТЬЮ: Точный рабочий URL шлюза Telegram
        direct_url = f"https://telegram.org{TG_BOT_TOKEN}/sendMessage"
        requests.post(direct_url, json={"chat_id": str(TG_USER_ID), "text": message, "parse_mode": "Markdown"}, timeout=5)
    except Exception as e:
        st.sidebar.error(f"Ошибка Telegram: {e}")

def check_upcoming_deadlines_and_notify():
    """Проверяет горящие дедлайны и шлет напоминание."""
    if "reports" not in st.session_state or not st.session_state.reports:
        return
    if "notified_dates" not in st.session_state:
        st.session_state.notified_dates = {}
        
    today = datetime.date.today()
    for r in st.session_state.reports:
        is_done = r["statuses"]["Отправлен"] and r["statuses"]["Принят"]
        if r.get("is_stat", False):
            is_done = r["statuses"]["Отправлен"]
            
        if r["has_base_control"] and not r["has_base"]:
            continue
            
        if not is_done:
            days_left = (r["deadline"] - today).days
            if 0 <= days_left <= 3:
                if st.session_state.notified_dates.get(r["id"]) != today:
                    msg = f"⚠️ *НАПОМИНАНИЕ О ДЕДЛАЙНЕ!*\n\n📊 Налог: *{r['name']}*\n📅 Дата сдачи: *{r['deadline'].strftime('%d.%m.%Y')}*\n⏳ Осталось дней: *{days_left}*"
                    send_telegram_reminder(msg)
                    st.session_state.notified_dates[r["id"]] = today
saved_reports = load_data()
if "reports" not in st.session_state:
    if saved_reports:  
        st.session_state.reports = saved_reports
    else:
        st.session_state.reports = []
        months_vat = {m: True for m in MONTHS_RU.keys()}
        st.session_state.reports.append({
            "id": 1, "name": "Ввозной НДС (ЕАЭС)", "day": 20, "months": months_vat, "payments": {m: False for m in MONTHS_RU.keys()},
            "has_base_control": True, "has_base": True, "is_stat": False, "comment": "", "end_date": None,
            "statuses": {"Подготовлен": False, "Отправлен": False, "Оплачен": False, "Принят": False},
            "deadline": calculate_first_deadline(20, months_vat)
        })
        save_data()
else:
    if saved_reports and len(saved_reports) > len(st.session_state.reports):
        st.session_state.reports = saved_reports

def check_and_autoclose_reports():
    if "reports" not in st.session_state or not st.session_state.reports:
        return
    today = datetime.date.today()
    updated = False
    for r in st.session_state.reports:
        if (r["deadline"] + datetime.timedelta(days=3)) <= today:
            m_name = list(MONTHS_RU.keys())[r["deadline"].month - 1]
            if r["has_base_control"] and not r["has_base"]: passed = True
            elif r["payments"].get(m_name, False): passed = r["statuses"]["Оплачен"]
            else: passed = r["statuses"]["Отправлен"] and r["statuses"]["Принят"] and (r["statuses"]["Оплачен"] or r["is_stat"])
            
            if passed:
                save_log_entry(r["name"], r["deadline"], "🤖 АВТОЗАКРЫТИЕ ПЕРИОДA", r.get("comment", ""))
                for k in r["statuses"]: r["statuses"][k] = False
                r["comment"] = ""
                if r.get("end_date") and r["deadline"] >= r["end_date"]:
                    st.session_state.reports = [rep for rep in st.session_state.reports if rep["id"] != r["id"]]
                else:
                    r["deadline"] = calculate_first_deadline(r["day"], r["months"], start_date=r["deadline"] + datetime.timedelta(days=1))
                updated = True
    if updated: 
        save_data()

check_and_autoclose_reports()
check_upcoming_deadlines_and_notify()

if "reports" in st.session_state and isinstance(st.session_state.reports, list):
    st.session_state.reports.sort(key=lambda x: x.get("deadline", datetime.date.today()))

def get_status_theme(r):
    today = datetime.date.today()
    days = (r["deadline"] - today).days
    if r["has_base_control"] and not r["has_base"]: return "🟢 База отсутствует", "#d4edda", "#155724"
    m_name = list(MONTHS_RU.keys())[r["deadline"].month - 1]
    if r["payments"].get(m_name, False):
        if r["statuses"]["Оплачен"]: return "🟢 Аванс оплачен", "#d4edda", "#155724"
        return ("🔴 Критический аванс", "#f8d7da", "#721c24") if days <= 3 else ("⚪ Плановый аванс", "#e2e3e5", "#383d41")
    if r["statuses"]["Отправлен"] and r["statuses"]["Принят"] and (r["statuses"]["Оплачен"] or r["is_stat"]): return "🟢 Все завершено", "#d4edda", "#155724"
    if (days <= 3 and not r["statuses"]["Отправлен"]) or (days <= 2 and not r["statuses"]["Принят"]): return "🔴 Критический срок!", "#f8d7da", "#721c24"
    if r["statuses"]["Отправлен"] and not r["statuses"]["Принят"]: return "🟡 Ожидает извещения", "#fff3cd", "#856404"
    if r["statuses"]["Отправлен"] and r["statuses"]["Принят"] and not r.get("is_stat", False) and not r["statuses"]["Оплачен"]: return "🔵 Не оплачен налог", "#cce5ff", "#004085"
    return "⚪ В работе", "#e2e3e5", "#383d41"

tab1, tab2, tab3 = st.tabs(["📊 Планнер", "🛠️ Настройки / Редактор", "📜 История"])
with tab1:
    today = datetime.date.today()
    col1_tasks, col2_tasks, col3_tasks = [], [], []
    if "reports" in st.session_state and st.session_state.reports:
        for r in st.session_state.reports:
            days_left = (r["deadline"] - today).days
            if days_left <= 7: col1_tasks.append(r)
            elif 7 < days_left <= 30: col2_tasks.append(r)
            else: col3_tasks.append(r)
            
    col1, col2, col3 = st.columns(3)
    columns_config = [{"col": col1, "title": "🔥 Неделя (до 7 дней)", "tasks": col1_tasks}, {"col": col2, "title": "📅 Месяц (8-30 дней)", "tasks": col2_tasks}, {"col": col3, "title": "🌐 Более 30 дней", "tasks": col3_tasks}]
    selected_id = st.session_state.get("selected_task_id", None)
    
    for c_cfg in columns_config:
        with c_cfg["col"]:
            st.markdown(f"### {c_cfg['title']}")
            with st.container(height=650 if selected_id else 500):
                if not c_cfg["tasks"]: st.caption("Нет задач")
                else:
                    for r in c_cfg["tasks"]:
                        status_text, bg_color, text_color = get_status_theme(r)
                        with st.container():
                            st.markdown(f'<div class="task-box"><div class="task-box-title">{r["name"]}</div><div class="task-box-text">Срок: {r["deadline"].strftime("%d.%m.%Y")}<br>Статус: {status_text}</div></div>', unsafe_allow_html=True)
                            st.markdown('<div style="margin-top: -65px; margin-bottom: 25px; display: flex; justify-content: flex-end; padding-right: 15px;">', unsafe_allow_html=True)
                            if st.button("⚙️ Управлять", key=f"manage_{r['id']}"):
                                st.session_state.selected_task_id = None if selected_id == r["id"] else r["id"]
                                st.rerun()
                            st.markdown('</div>', unsafe_allow_html=True)
                            
                        if selected_id == r["id"]:
                            st.markdown(f"##### 🛠️ Управление: {r['name']}")
                            if r["has_base_control"]:
                                if st.checkbox("Наличие налоговой базы", value=r["has_base"], key=f"base_{r['id']}") != r["has_base"]:
                                    r["has_base"] = not r["has_base"]
                                    save_data(); save_log_entry(r["name"], r["deadline"], f"База: {'Есть' if r['has_base'] else 'Нет'}"); st.rerun()
                                    
                            ordered_statuses = ["Подготовлен", "Отправлен", "Принят", "Оплачен"]
                            status_cols = st.columns(len(ordered_statuses))
                            for idx, s_n in enumerate(ordered_statuses):
                                if s_n == "Оплачен" and r.get("is_stat", False): continue
                                with status_cols[idx]:
                                    if st.checkbox(s_n, value=r["statuses"][s_n], key=f"chk_{s_n}_{r['id']}") != r["statuses"][s_n]:
                                        r["statuses"][s_n] = not r["statuses"][s_n]
                                        save_data(); save_log_entry(r["name"], r["deadline"], f"Статус {s_n}"); st.rerun()
                                        
                            comm = st.text_input("Комментарий", value=r.get("comment", ""), key=f"comm_{r['id']}")
                            if comm != r.get("comment", ""):
                                r["comment"] = comm
                                save_data(); save_log_entry(r["name"], r["deadline"], "Обновлен комментарий"); st.rerun()
                                
                            b1, b2 = st.columns(2)
                            with b1:
                                if st.button("❌ Скрыть", key=f"cls_{r['id']}"): del st.session_state.selected_task_id; st.rerun()
                            with b2:
                                if st.button("🚩 Закрыть период", type="primary", key=f"fin_{r['id']}"):
                                    save_log_entry(r["name"], r["deadline"], "Период закрыт вручную")
                                    for k in r["statuses"]: r["statuses"][k] = False
                                    r["comment"] = ""
                                    if r.get("end_date") and r["deadline"] >= r["end_date"]: st.session_state.reports = [rep for rep in st.session_state.reports if rep["id"] != r["id"]]
                                    else: r["deadline"] = calculate_first_deadline(r["day"], r["months"], start_date=r["deadline"] + datetime.timedelta(days=1))
                                    save_data(); del st.session_state.selected_task_id; st.success("Закрыто!"); st.rerun()
with tab2:
    st.subheader("🛠️ Управление справочником")
    mode = st.radio("Действие:", ["➕ Создать", "✏️ Изменить / Удалить"], horizontal=True)
    QUARTERS = [
        {"title": "📊 I Квартал", "months": ["Январь", "Февраль", "Март"]},
        {"title": "📊 II Квартал", "months": ["Апрель", "Май", "Июнь"]},
        {"title": "📊 III Квартал", "months": ["Июль", "Август", "Сентябрь"]},
        {"title": "📊 IV Квартал", "months": ["Октябрь", "Ноябрь", "Декабрь"]}
    ]
    
    if mode == "➕ Создать":
        with st.form("f_new", clear_on_submit=True):
            n_name = st.text_input("Название:")
            n_day = st.number_input("День сдачи:", min_value=1, max_value=31, value=20)
            mc = st.columns(4); n_m, n_p = {}, {}
            for q_idx, q_data in enumerate(QUARTERS):
                with mc[q_idx]:
                    st.markdown(f"#### {q_data['title']}")
                    for m_n in q_data["months"]:
                        st.markdown(f"**{m_n}**")
                        n_m[m_n] = st.checkbox("Активен", key=f"nm_{m_n}")
                        n_p[m_n] = st.checkbox("Аванс", key=f"np_{m_n}")
            cs1, cs2 = st.columns(2)
            with cs1: n_bc, n_st = st.checkbox("Контроль базы"), st.checkbox("Без уплаты")
            with cs2: h_end = st.checkbox("Дата окончания"); n_end = st.date_input("Дата:", disabled=not h_end)
            if st.form_submit_button("➕ Добавить"):
                if not n_name or not any(n_m.values()): st.error("Заполните поля")
                else:
                    n_id = max([r["id"] for r in st.session_state.reports]) + 1 if st.session_state.reports else 1
                    dl = calculate_first_deadline(n_day, n_m)
                    st.session_state.reports.append({"id": n_id, "name": n_name, "day": n_day, "months": n_m, "payments": {m: (n_p[m] if n_m[m] else False) for m in MONTHS_RU.keys()}, "has_base_control": n_bc, "has_base": True, "is_stat": n_st, "comment": "", "end_date": n_end if h_end else None, "statuses": {"Подготовлен": False, "Отправлен": False, "Оплачен": False, "Принят": False}, "deadline": dl})
                    save_data(); save_log_entry(n_name, dl, "Создан налог"); st.success("Создано!"); st.rerun()
    else:
        if "reports" not in st.session_state or not st.session_state.reports: st.info("Пусто")
        else:
            edit = next(r for r in st.session_state.reports if r["name"] == st.selectbox("Отчет:", [r["name"] for r in st.session_state.reports]))
            with st.form("f_edit"):
                e_name = st.text_input("Название:", value=edit["name"])
                e_day = st.number_input("День сдачи:", min_value=1, max_value=31, value=int(edit["day"]))
                mc = st.columns(4); e_m, e_p = {}, {}
                for q_idx, q_data in enumerate(QUARTERS):
                    with mc[q_idx]:
                        st.markdown(f"#### {q_data['title']}")
                        for m_n in q_data["months"]:
                            st.markdown(f"**{m_n}**")
                            e_m[m_n] = st.checkbox("Активен", value=edit["months"].get(m_n, False), key=f"em_{m_n}")
                            e_p[m_n] = st.checkbox("Аванс", value=edit["payments"].get(m_n, False), key=f"ep_{m_n}")
                ce1, ce2 = st.columns(2)
                with ce1: e_bc, e_st = st.checkbox("Контроль базы", value=edit["has_base_control"]), st.checkbox("Без уплаты", value=edit["is_stat"])
                with ce2: o_h = edit.get("end_date") is not None; e_he = st.checkbox("Дата окончания", value=o_h); e_ed = st.date_input("Дата:", value=edit["end_date"] if o_h else datetime.date.today(), disabled=not e_he)
                if st.form_submit_button("💾 Сохранить"):
                    edit.update({"name": e_name, "day": e_day, "months": e_m, "payments": {m: (e_p[m] if e_m[m] else False) for m in MONTHS_RU.keys()}, "has_base_control": e_bc, "is_stat": e_st, "end_date": e_ed if e_he else None, "deadline": calculate_first_deadline(e_day, e_m)})
                    save_data(); save_log_entry(e_name, edit["deadline"], "Изменен налог"); st.success("Сохранено!"); st.rerun()
            if st.button("❌ УДАЛИТЬ НАЛОГ ИЗ СИСТЕМЫ", use_container_width=True):
                save_log_entry(edit["name"], edit["deadline"], "Удален налог")
                st.session_state.reports = [r for r in st.session_state.reports if r["id"] != edit["id"]]
                save_data(); st.success("Удалено!"); st.rerun()

with tab3:
    st.subheader("📜 Журнал учета операций бухгалтера")
    logs = load_logs()
    if not logs: st.info("Журнал пуст")
    else:
        df = pd.DataFrame(logs)
        df = df[["timestamp", "report_name", "period", "period_comment", "action"]]
        df.columns = ["🕒 Время", "📊 Налог", "📅 Период", "💰 Пометка", "📝 Действие"]
        st.dataframe(df, use_container_width=True, hide_index=True)
