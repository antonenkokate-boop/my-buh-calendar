import datetime
import calendar
import json
import os
import streamlit as st
import requests
import pandas as pd

# Настройка страницы под мобильные устройства и десктоп
st.set_page_config(page_title="Календарь бухгалтера РБ", layout="wide", page_icon="📅")

# HTML-стили для отображения карточек налогов
st.markdown("""
    <style>
    .task-card {
        padding: 12px;
        border-radius: 8px;
        margin-bottom: 10px;
        border-left: 5px solid;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        background-color: #ffffff;
    }
    .task-title {
        font-weight: bold;
        font-size: 0.95rem;
        margin-bottom: 4px;
        color: #333333;
    }
    .task-details {
        font-size: 0.85rem;
        color: #555555;
    }
    </style>
""", unsafe_allow_html=True)

DB_FILE = "database.json"
LOG_FILE = "history_logs.json"

# --- 1. ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ И ЛОГАМИ ---
def load_data():
    """Загружает данные налогов из JSON."""
    if not os.path.exists(DB_FILE):
        return None
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
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
    """Сохраняет текущее состояние налогов в JSON."""
    try:
        serializable_reports = []
        for r in st.session_state.reports:
            r_copy = r.copy()
            if isinstance(r_copy["deadline"], datetime.date):
                r_copy["deadline"] = r_copy["deadline"].strftime("%Y-%m-%d")
            if r_copy.get("end_date") and isinstance(r_copy["end_date"], datetime.date):
                r_copy["end_date"] = r_copy["end_date"].strftime("%Y-%m-%d")
            serializable_reports.append(r_copy)
            
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable_reports, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"Ошибка сохранения базы данных: {e}")

def load_logs():
    """Загружает историю действий бухгалтера."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_log_entry(report_name, target_date, action_text, current_comment=""):
    """Добавляет запись в журнал истории действий."""
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
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=4)
    except Exception:
        pass
# --- НАСТРОЙКА ТЕЛЕГРАМ-УВЕДОМЛЕНИЙ (ПОДКЛЮЧЕНО) ---
TG_BOT_TOKEN = "8807247946:AAHWnh-5y1PzA13VvoJPgzsh0Ne-X13pXdo"
TG_USER_ID = "631793577"

# --- 2. ФУНКЦИЯ ПРОИЗВОДСТВЕННОГО КАЛЕНДАРЯ РБ ---
def get_real_working_day(date_check):
    """Сдвигает дедлайн вперед, если он выпал на выходной или праздник в РБ."""
    while True:
        try:
            url = f"https://isdayoff.ru{date_check.year}&month={date_check.month:02d}&day={date_check.day:02d}&cc=by"
            response = requests.get(url, timeout=2)
            if response.status_code == 200 and response.text in ["1", "2"]:
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

# --- ФУНКЦИЯ ОТПРАВКИ УВЕДОМЛЕНИЙ В TELEGRAM ---
def send_telegram_reminder(message):
    """Отправляет текстовое уведомление через созданного бота."""
    if not TG_BOT_TOKEN or not TG_USER_ID:
        return
    try:
        url = f"https://telegram.org{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_USER_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=3)
    except Exception:
        pass

def check_upcoming_deadlines_and_notify():
    """Проверяет горящие дедлайны и шлет напоминание."""
    if "notified_dates" not in st.session_state:
        st.session_state.notified_dates = {}
        
    today = datetime.date.today()
    for r in st.session_state.reports:
        # Проверяем сдачу с учетом признака "Отчет без уплаты" (is_stat)
        is_done = r["statuses"]["Отправлен"] and r["statuses"]["Принят"]
        if r.get("is_stat", False):
            is_done = r["statuses"]["Отправлен"]
            
        if r["has_base_control"] and not r["has_base"]:
            continue
            
        if not is_done:
            days_left = (r["deadline"] - today).days
            if 0 <= days_left <= 3:
                last_notify_date = st.session_state.notified_dates.get(r["id"])
                if last_notify_date != today:
                    msg = f"⚠️ *НАПОМИНАНИЕ О ДЕДЛАЙНЕ!*\n\n📊 Налог: *{r['name']}*\n📅 Дата сдачи: *{r['deadline'].strftime('%d.%m.%Y')}*\n⏳ Осталось дней: *{days_left}*"
                    send_telegram_reminder(msg)
                    st.session_state.notified_dates[r["id"]] = today

# --- 3. ИНИЦИАЛИЗАЦИЯ ИЛИ ЗАГРУЗКА ДАННЫХ В СЕССИЮ ---
saved_reports = load_data()

if "reports" not in st.session_state:
    if saved_reports is not None:
        st.session_state.reports = saved_reports
    else:
        st.session_state.reports = []
        months_vat = {m: True for m in MONTHS_RU.keys()}
        payments_vat = {m: False for m in MONTHS_RU.keys()}
        st.session_state.reports.append({
            "id": 1, "name": "Ввозной НДС (ЕАЭС)", "day": 20, "months": months_vat, "payments": payments_vat,
            "has_base_control": True, "has_base": True, "is_stat": False, "comment": "", "end_date": None,
            "statuses": {"Подготовлен": False, "Отправлен": False, "Оплачен": False, "Принят": False},
            "deadline": calculate_first_deadline(20, months_vat)
        })
        save_data()

# --- 4. АВТОМАТИЧЕСКАЯ ПРОВЕРКА И ЗАКРЫТИЕ ХВОСТОВ (Дедлайн + 3 дня) ---
def check_and_autoclose_reports():
    today = datetime.date.today()
    updated = False
    for r in st.session_state.reports:
        if (r["deadline"] + datetime.timedelta(days=3)) <= today:
            m_name = list(MONTHS_RU.keys())[r["deadline"].month - 1]
            is_pay = r["payments"].get(m_name, False)
            passed = False
            if r["has_base_control"] and not r["has_base"]: passed = True
            elif is_pay: passed = r["statuses"]["Оплачен"]
            else: passed = r["statuses"]["Отправлен"] and r["statuses"]["Принят"] and (r["statuses"]["Оплачен"] or r["is_stat"])
            
            if passed:
                save_log_entry(r["name"], r["deadline"], "🤖 АВТОЗАКРЫТИЕ ПЕРИОДA (Выполнено, прошло 3+ дня)", r.get("comment", ""))
                for k in r["statuses"]: r["statuses"][k] = False
                r["comment"] = ""
                if r.get("end_date") and r["deadline"] >= r["end_date"]:
                    st.session_state.reports = [rep for rep in st.session_state.reports if rep["id"] != r["id"]]
                else:
                    r["deadline"] = calculate_first_deadline(r["day"], r["months"], start_date=r["deadline"] + datetime.timedelta(days=1))
                updated = True
    if updated:
        save_data()
        st.rerun()

check_and_autoclose_reports()
check_upcoming_deadlines_and_notify()
# --- 5. ЛОГИКА ЦВЕТОВОЙ ПОДДСВЕТКИ КАРТОЧЕК ---
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

# --- ВКЛАДКА 1: КАНБАН-ДОСКА (3 КОЛОНКИ) ---
with tab1:
    today = datetime.date.today()
    col1_tasks, col2_tasks, col3_tasks = [], [], []
    
    for r in st.session_state.reports:
        days_left = (r["deadline"] - today).days
        if days_left <= 7:
            col1_tasks.append(r)  # 🔥 Неделя
        elif 7 < days_left <= 30:
            col2_tasks.append(r)  # 📅 Месяц
        else:
            col3_tasks.append(r)  # 🌐 Более 30 дней

    col1, col2, col3 = st.columns(3)
    columns_config = [
        {"col": col1, "title": "🔥 Неделя (до 7 дней)", "tasks": col1_tasks},
        {"col": col2, "title": "📅 Месяц (8-30 дней)", "tasks": col2_tasks},
        {"col": col3, "title": "🌐 Более 30 дней", "tasks": col3_tasks}
    ]
    
    for c_cfg in columns_config:
        with c_cfg["col"]:
            st.markdown(f"### {c_cfg['title']}")
            with st.container(height=500):
                if not c_cfg["tasks"]:
                    st.caption("Нет задач")
                else:
                    for r in c_cfg["tasks"]:
                        status_text, bg_color, text_color = get_status_theme(r)
                        deadline_str = r["deadline"].strftime("%d.%m.%Y")
                        
                        card_html = f"""
                        <div class="task-card" style="border-left-color: {text_color};">
                            <div class="task-title" style="color: {text_color};">{r['name']}</div>
                            <div class="task-details">
                                <b>Срок:</b> {deadline_str}<br>
                                <b>Статус:</b> {status_text}
                            </div>
                        </div>
                        """
                        st.markdown(card_html, unsafe_allow_html=True)
                        if st.button("⚙️ Управлять", key=f"manage_{r['id']}"):
                            st.session_state.selected_task_id = r["id"]

    if "selected_task_id" in st.session_state:
        st.markdown("---")
        task_id = st.session_state.selected_task_id
        task = next((rep for rep in st.session_state.reports if rep["id"] == task_id), None)
        
        if task:
            st.subheader(f"🛠️ Управление: {task['name']}")
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                st.info(f"📅 Дедлайн: **{task['deadline'].strftime('%d.%m.%Y')}**")
                if task["has_base_control"]:
                    old_base = task["has_base"]
                    task["has_base"] = st.checkbox("Наличие налоговой базы", value=task["has_base"], key=f"base_{task_id}")
                    if old_base != task["has_base"]:
                        save_data()
                        # ИСПРАВЛЕНО: Автоматическое мгновенное логирование изменения базы
                        base_status = "Есть" if task["has_base"] else "Отсутствует"
                        save_log_entry(task["name"], task["deadline"], f"Изменено наличие базы: {base_status}", task.get("comment", ""))
                        st.rerun()
            with cc2:
                st.write("**Чек-лист выполнения:**")
                for status_name in task["statuses"].keys():
                    if status_name == "Оплачен" and task.get("is_stat", False):
                        continue
                        
                    old_val = task["statuses"][status_name]
                    task["statuses"][status_name] = st.checkbox(status_name, value=task["statuses"][status_name], key=f"chk_{status_name}_{task_id}")
                    
                    # ИСПРАВЛЕНО: Мгновенное авто-логирование каждого клика по чекбоксу
                    if old_val != task["statuses"][status_name]:
                        save_data()
                        ch_status = "Включено" if task["statuses"][status_name] else "Выключено"
                        save_log_entry(task["name"], task["deadline"], f"Статус '{status_name}': {ch_status}", task.get("comment", ""))
                        st.rerun()
            with cc3:
                old_comm = task.get("comment", "")
                task["comment"] = st.text_input("Комментарий к периоду", value=old_comm, key=f"comm_{task_id}")
                if old_comm != task["comment"]:
                    save_data()
                    # ИСПРАВЛЕНО: Мгновенное авто-логирование изменения комментария при потере фокуса / Enter
                    save_log_entry(task["name"], task["deadline"], f"Обновлен комментарий периода", task["comment"])
                    st.rerun()
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                if st.button("🏁 Закрыть период и перенести дедлайн", type="primary", key="close_period_btn", use_container_width=True):
                    active_steps = [k for k, v in task["statuses"].items() if v and not (k == "Оплачен" and task.get("is_stat", False))]
                    if not active_steps:
                        active_steps = ["Без отметок"]
                    action_detail = f"🏁 ПЕРИОД ЗАКРЫТ ВРУЧНУЮ. Выполненные шаги: {', '.join(active_steps)}"
                    
                    save_log_entry(task["name"], task["deadline"], action_detail, task["comment"])
                    
                    for k in task["statuses"]:
                        task["statuses"][k] = False
                    task["comment"] = ""
                    
                    if task.get("end_date") and task["deadline"] >= task["end_date"]:
                        st.session_state.reports = [rep for rep in st.session_state.reports if rep["id"] != task["id"]]
                    else:
                        task["deadline"] = calculate_first_deadline(task["day"], task["months"], start_date=task["deadline"] + datetime.timedelta(days=1))
                    
                    save_data()
                    del st.session_state.selected_task_id
                    st.success("Период успешно закрыт!")
                    st.rerun()
            with c_btn2:
                if st.button("❌ Закрыть панель", key="close_panel_btn", use_container_width=True):
                    del st.session_state.selected_task_id
                    st.rerun()
# --- ВКЛАДКА 2: НАСТРОЙКИ СПРАВОЧНИКА НАЛОГОВ ---
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
            
            st.write("**Выберите месяцы сдачи и настройте авансовые платежи (поквартально):**")
            mc = st.columns(4); n_m, n_p = {}, {}
            for q_idx, q_data in enumerate(QUARTERS):
                with mc[q_idx]:
                    st.markdown(f"#### {q_data['title']}")
                    for m_n in q_data["months"]:
                        st.markdown(f"**{m_n}**")
                        n_m[m_n] = st.checkbox("Активен", key=f"nm_{m_n}")
                        n_p[m_n] = st.checkbox("Только платеж (аванс)", key=f"np_{m_n}")
                        st.write("")
                    
            st.divider()
            cs1, cs2 = st.columns(2)
            with cs1:
                n_bc = st.checkbox("Только при наличии базы")
                n_st = st.checkbox("Отчет без уплаты")
            with cs2:
                h_end = st.checkbox("Задать дату окончания действия налога")
                n_end = st.date_input("Дата окончания:", value=datetime.date.today()+datetime.timedelta(days=365), disabled=not h_end)
                
            if st.form_submit_button("➕ Добавить"):
                if not n_name or not any(n_m.values()): 
                    st.error("Заполните название и выберите хотя бы один активный месяц.")
                else:
                    final_p = {m: (n_p[m] if n_m[m] else False) for m in MONTHS_RU.keys()}
                    n_id = max([r["id"] for r in st.session_state.reports]) + 1 if st.session_state.reports else 1
                    dl = calculate_first_deadline(n_day, n_m)
                    
                    st.session_state.reports.append({
                        "id": n_id, "name": n_name, "day": n_day, "months": n_m, "payments": final_p, 
                        "has_base_control": n_bc, "has_base": True, "is_stat": n_st, "comment": "", 
                        "end_date": n_end if h_end else None, 
                        "statuses": {"Подготовлен": False, "Отправлен": False, "Оплачен": False, "Принят": False}, 
                        "deadline": dl
                    })
                    save_data(); save_log_entry(n_name, dl, "Создан новый налог в справочнике"); st.success("Создано!"); st.rerun()
                    
    else:
        if not st.session_state.reports: 
            st.info("Список отчетов пуст.")
        else:
            names = [r["name"] for r in st.session_state.reports]
            s_name = st.selectbox("Выберите отчет для редактирования:", names, key="select_edit_report")
            edit = next(r for r in st.session_state.reports if r["name"].strip() == s_name.strip())
            
            with st.form("f_edit"):
                e_name = st.text_input("Название:", value=edit["name"])
                e_day = st.number_input("День сдачи:", min_value=1, max_value=31, value=int(edit["day"]))
                
                st.write("**Месяцы сдачи и авансы (поквартально):**")
                mc = st.columns(4); e_m, e_p = {}, {}
                for q_idx, q_data in enumerate(QUARTERS):
                    with mc[q_idx]:
                        st.markdown(f"#### {q_data['title']}")
                        for m_n in q_data["months"]:
                            st.markdown(f"**{m_n}**")
                            was_act = edit["months"].get(m_n, False)
                            was_pay = edit["payments"].get(m_n, False)
                            
                            e_m[m_n] = st.checkbox("Активен", value=was_act, key=f"em_{m_n}_{edit['id']}")
                            e_p[m_n] = st.checkbox("Только платеж (аванс)", value=was_pay, key=f"ep_{m_n}_{edit['id']}")
                            st.write("")
                        
                st.divider()
                ce1, ce2 = st.columns(2)
                with ce1:
                    e_bc = st.checkbox("Только при наличии базы", value=edit["has_base_control"])
                    e_st = st.checkbox("Отчет без уплаты", value=edit["is_stat"])
                with ce2:
                    o_h = edit.get("end_date") is not None
                    e_he = st.checkbox("Установить дату завершения налога", value=o_h)
                    e_ed = st.date_input("Дата окончания:", value=edit["end_date"] if o_h else datetime.date.today()+datetime.timedelta(days=365), disabled=not e_he)
                    
                if st.form_submit_button("💾 Сохранить изменения"):
                    if not e_name or not any(e_m.values()): 
                        st.error("Название не может быть пустым, должен быть выбран хотя бы один месяц.")
                    else:
                        final_ep = {m: (e_p[m] if e_m[m] else False) for m in MONTHS_RU.keys()}
                        edit.update({
                            "name": e_name, "day": e_day, "months": e_m, "payments": final_ep, 
                            "has_base_control": e_bc, "is_stat": e_st, "end_date": e_ed if e_he else None
                        })
                        edit["deadline"] = calculate_first_deadline(e_day, e_m)
                        save_data(); save_log_entry(e_name, edit["deadline"], "Изменены параметры расписания налогов"); st.success("Обновлено!"); st.rerun()
                        
            st.divider()
            st.write("**Опасная зона:**")
            if st.button("❌ ПОЛНОСТЬЮ УДАЛИТЬ НАЛОГ ИЗ СИСТЕМЫ", use_container_width=True):
                save_log_entry(edit["name"], edit["deadline"], "УДАЛЕНО ИЗ СИСТЕМЫ")
                st.session_state.reports = [r for r in st.session_state.reports if r["id"] != edit["id"]]
                if "active_report_id" in st.session_state: 
                    del st.session_state["active_report_id"]
                save_data(); st.success("Удалено!"); st.rerun()

# --- ВКЛАДКА 3: ЖУРНАЛ ИСТОРИИ ДЕЙСТВИЙ ---
with tab3:
    st.subheader("📜 Журнал учета операций бухгалтера")
    logs = load_logs()
    if not logs: 
        st.info("Журнал пуст")
    else:
        df = pd.DataFrame(logs)
        if "period_comment" not in df.columns: 
            df["period_comment"] = ""
        df = df[["timestamp", "report_name", "period", "period_comment", "action"]]
        df.columns = ["🕒 Время фиксации", "📊 Вид налога", "📅 Отчетный период", "💰 Пометка / Сумма периода", "📝 Совершенное действие"]
        st.dataframe(df, use_container_width=True, hide_index=True)
