import streamlit as st
import pandas as pd
from datetime import datetime, time
import io
import pdfplumber  # NEW: used to extract text from the guest PDF

# --- ALL FUNCTIONS DEFINED FIRST ---
# Python reads top to bottom, so every function must be defined before it's called.
# Think of this section like your static methods in Java — defined once, usable anywhere below.

# --- GUEST MATCHING FUNCTIONS ---

# Maps every US state abbreviation to one of five regions.
# Think of this like a Java HashMap<String, String>.
STATE_REGIONS = {
    "ME": "Northeast", "NH": "Northeast", "VT": "Northeast", "MA": "Northeast",
    "RI": "Northeast", "CT": "Northeast", "NY": "Northeast", "NJ": "Northeast",
    "PA": "Northeast",
    "MD": "Southeast", "DE": "Southeast", "VA": "Southeast", "WV": "Southeast",
    "NC": "Southeast", "SC": "Southeast", "GA": "Southeast", "FL": "Southeast",
    "AL": "Southeast", "MS": "Southeast", "TN": "Southeast", "KY": "Southeast",
    "AR": "Southeast", "LA": "Southeast",
    "OH": "Midwest", "MI": "Midwest", "IN": "Midwest", "IL": "Midwest",
    "WI": "Midwest", "MN": "Midwest", "IA": "Midwest", "MO": "Midwest",
    "ND": "Midwest", "SD": "Midwest", "NE": "Midwest", "KS": "Midwest",
    "TX": "Southwest", "OK": "Southwest", "NM": "Southwest", "AZ": "Southwest",
    "CO": "West", "WY": "West", "MT": "West", "ID": "West", "UT": "West",
    "NV": "West", "CA": "West", "OR": "West", "WA": "West", "AK": "West",
    "HI": "West"
}

def parse_location(location_str):
    """
    Splits a location string into (city, state, region).
    Handles TWO formats:
      - Staff roster:  'Columbus, OH'           comma-separated
      - Guest PDF:     'Rancho Bernardo (CA)'   state in parentheses at end
    Returns lowercase city for case-insensitive comparison.
    """
    import re
    if not location_str or pd.isna(location_str):
        return None, None, None
    location_str = str(location_str).strip()

    # FIXED: detect guest PDF format — state code in parentheses at end
    # e.g. 'Rancho Bernardo (CA)' or 'Clovis West (CA)'
    paren_match = re.search(r'\(([A-Z]{2})\)\s*$', location_str)
    if paren_match:
        state = paren_match.group(1).upper()
        city = location_str[:paren_match.start()].strip().lower()
        region = STATE_REGIONS.get(state)
        return city, state, region

    # Staff roster format: 'City, ST'
    parts = location_str.split(",")
    city = parts[0].strip().lower() if len(parts) >= 1 else None
    state = parts[1].strip().upper()[:2] if len(parts) >= 2 else None
    region = STATE_REGIONS.get(state) if state else None
    return city, state, region

def extract_guests_from_pdf(pdf_file):
    """
    Reads the guest PDF and extracts name (col 1) and location (col 2).
    Uses pdfplumber to parse the table — works on clean digital PDFs.
    Returns a list of dicts: [{'name': ..., 'location': ...}, ...]
    """
    guests = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                # Skip empty rows or header rows
                if not row or not row[0]:
                    continue
                name = str(row[0]).strip()
                location = str(row[1]).strip() if len(row) > 1 else ""
                # Skip if it looks like a header (contains 'name' or 'guest')
                if name.lower() in ["name", "guest", "guest name", ""]:
                    continue
                guests.append({"name": name, "location": location})
    return guests

def match_hosts_to_guests(scheduled_names, staff_roster_df, guests):
    """
    Matches each scheduled host to one guest using 4-tier location logic:
      Tier 1: Same city
      Tier 2: Same state
      Tier 3: Same region
      Tier 4: Anyone remaining (unmatched)

    scheduled_names: set of full name strings from the generated schedule
    staff_roster_df: DataFrame with columns First, Last, Hometown (cols A, B, C)
    guests: list of dicts from extract_guests_from_pdf()

    Returns a DataFrame with columns: Host, Guest, Host Hometown, Guest Location, Match Quality
    """
    # Build a lookup: full name → hometown for scheduled staff only
    # FIXED: staff roster now read with header=0, so columns are named
    # 'First Name', 'Last Name', 'Hometown' — use those names directly.
    host_lookup = {}
    for _, row in staff_roster_df.iterrows():
        first = str(row["First Name"]).strip()
        last = str(row["Last Name"]).strip()
        full_name = f"{first} {last}"
        hometown = str(row["Hometown"]).strip()
        # Only include staff who are actually scheduled today
        # We check if this name appears anywhere in the scheduled set (case-insensitive)
        for sched_name in scheduled_names:
            if full_name.lower() in sched_name.lower() or sched_name.lower() in full_name.lower():
                host_lookup[sched_name] = hometown
                break

    # FIXED: multi-pass matching instead of greedy single-pass.
    # Old approach: loop through hosts in order, each one immediately grabs the
    # best guest available — so early hosts waste good guests that later hosts need.
    #
    # New approach: four separate passes, one per tier. In each pass we only lock
    # in matches at that quality level. Hosts that didn't match in Pass 1 move to
    # Pass 2, and so on. No guest is ever assigned to a low-quality match when a
    # better host for them is still waiting.
    #
    # Think of it like a draft: everyone submits their top pick simultaneously,
    # conflicts are resolved, then everyone submits their second pick, etc.

    available_guests = guests.copy()
    results = {}  # host_name -> result row, filled across all passes
    unmatched_hosts = list(host_lookup.items())  # list of (name, hometown) tuples

    # --- Pass 1: Same City ---
    still_unmatched = []
    for host_name, host_hometown in unmatched_hosts:
        h_city, _, _ = parse_location(host_hometown)
        matched_guest = None
        for g in available_guests:
            g_city, _, _ = parse_location(g["location"])
            if h_city and g_city and h_city == g_city:
                matched_guest = g
                break
        if matched_guest:
            available_guests.remove(matched_guest)
            results[host_name] = {"Host": host_name, "Host Hometown": host_hometown,
                "Guest": matched_guest["name"], "Guest Location": matched_guest["location"],
                "Match Quality": "✅ Same City"}
        else:
            still_unmatched.append((host_name, host_hometown))
    unmatched_hosts = still_unmatched

    # --- Pass 2: Same State ---
    still_unmatched = []
    for host_name, host_hometown in unmatched_hosts:
        _, h_state, _ = parse_location(host_hometown)
        matched_guest = None
        for g in available_guests:
            _, g_state, _ = parse_location(g["location"])
            if h_state and g_state and h_state == g_state:
                matched_guest = g
                break
        if matched_guest:
            available_guests.remove(matched_guest)
            results[host_name] = {"Host": host_name, "Host Hometown": host_hometown,
                "Guest": matched_guest["name"], "Guest Location": matched_guest["location"],
                "Match Quality": "🟡 Same State"}
        else:
            still_unmatched.append((host_name, host_hometown))
    unmatched_hosts = still_unmatched

    # --- Pass 3: Same Region ---
    still_unmatched = []
    for host_name, host_hometown in unmatched_hosts:
        _, _, h_region = parse_location(host_hometown)
        matched_guest = None
        for g in available_guests:
            _, _, g_region = parse_location(g["location"])
            if h_region and g_region and h_region == g_region:
                matched_guest = g
                break
        if matched_guest:
            available_guests.remove(matched_guest)
            results[host_name] = {"Host": host_name, "Host Hometown": host_hometown,
                "Guest": matched_guest["name"], "Guest Location": matched_guest["location"],
                "Match Quality": "🟠 Same Region"}
        else:
            still_unmatched.append((host_name, host_hometown))
    unmatched_hosts = still_unmatched

    # --- Pass 4: Whoever is left ---
    for host_name, host_hometown in unmatched_hosts:
        if available_guests:
            matched_guest = available_guests.pop(0)
            results[host_name] = {"Host": host_name, "Host Hometown": host_hometown,
                "Guest": matched_guest["name"], "Guest Location": matched_guest["location"],
                "Match Quality": "⚪ No Geographic Match"}
        else:
            results[host_name] = {"Host": host_name, "Host Hometown": host_hometown,
                "Guest": "⚠️ No guest available", "Guest Location": "—",
                "Match Quality": "⚠️ Unassigned"}

    return pd.DataFrame(results.values())

# --- TEMPLATE GENERATOR ---
# Defined here at the top so it's available when the download button renders in the UI.
def generate_template():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # No header row — matches exactly how the master sheet tabs are structured
        example_data = {
            "A": ["Kai Switzer", "Madison Herbert", "Trenton Wells"],
            "B": ["8am-4pm", "Available all day!", "10am-2pm"]
        }
        pd.DataFrame(example_data).to_excel(writer, index=False, header=False, sheet_name='Data_Entry')

        instructions = {
            "Step": ["1", "2", "3", "4", "5", "—", "—", "—"],
            "What To Do": [
                "Open the master availability Excel file",
                "Click the tab for today's practice date",
                "Select all rows in Column A (names) and Column B (availability)",
                "Copy and paste into cell A1 of this template file (Data_Entry tab)",
                "Save this file and upload it to the scheduling tool",
                "FORMAT REMINDER: Column A = full staff name",
                "FORMAT REMINDER: Column B = availability, e.g. '8am-4pm' or 'Available all day!'",
                "FORMAT REMINDER: No header row needed — start data in row 1"
            ]
        }
        pd.DataFrame(instructions).to_excel(writer, index=False, sheet_name='Instructions')
    return output.getvalue()

# --- 1. OSU FOOTBALL BRANDING ---
st.set_page_config(page_title="OSU Football Practice Scheduler", layout="wide", page_icon="🏈")

st.markdown("""
    <style>
    .stButton>button, .stDownloadButton>button {
        background-color: #bb0000 !important;
        color: white !important;
        border-radius: 4px;
        font-weight: bold;
    }
    .main-title { color: #bb0000; font-size: 42px; font-weight: bold; margin-bottom: 0px; }
    .sub-title { color: #666666; font-size: 20px; font-style: italic; margin-top: 0px; }
    [data-testid="stVerticalBlock"] img { margin-top: -10px; }

    /* NEW: instruction box styling */
    .instruction-box {
        background-color: #f9f9f9;
        border-left: 5px solid #bb0000;
        padding: 16px 20px;
        border-radius: 4px;
        margin-bottom: 16px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- LOGO & HEADER ---
col1, col2 = st.columns([1, 5])
with col1:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Ohio_State_Buckeyes_logo.svg/200px-Ohio_State_Buckeyes_logo.svg.png", width=100)
with col2:
    st.markdown('<p class="main-title">OHIO STATE FOOTBALL</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">Spring Practice Staffing Operations</p>', unsafe_allow_html=True)

st.divider()

# --- NEW: ALWAYS-VISIBLE HOW-TO INSTRUCTIONS ---
# Sits at the top so every user sees it before doing anything.
st.markdown("### 📋 How to Use This Tool")
st.markdown("""
<div class="instruction-box">
<b>Step 1 — Open the Master Availability Sheet</b><br>
Open the shared Excel file that contains all staff availability.<br><br>

<b>Step 2 — Find Today's Tab</b><br>
Each tab in the master sheet represents one practice date. Click the tab for the practice you are scheduling.<br><br>

<b>Step 3 — Copy the Two Columns</b><br>
Select <b>all rows in Column A (names) and Column B (availability)</b>. Do not include a header row — just the data.<br><br>

<b>Step 4 — Paste Into the Template & Save</b><br>
Download the template below, open it, and paste your data into cell A1 of the <b>Data_Entry</b> tab. Save the file as <b>.xlsx</b> on your computer.<br><br>

<b>Step 5 — Upload Below</b><br>
Use the file uploader on this page to upload your saved file. The schedule will generate automatically.<br><br>

<b>Step 6 — Adjust Settings if Needed (optional)</b><br>
Click <b>⚙️ SETTINGS & CONTROLS</b> above the upload button to customize the schedule:<br>
&nbsp;&nbsp;• <b>Priority Staff</b> — names listed here get assigned to Floater Lanes first. Edit to match your current roster.<br>
&nbsp;&nbsp;• <b>Recruit Lanes / Floater Lanes</b> — set how many of each lane type to generate.<br>
&nbsp;&nbsp;• <b>Practice Start &amp; End Time</b> — set the window the scheduler should fill. Availability outside this window is ignored.<br>
&nbsp;&nbsp;• <b>Minimum Hours</b> — any staff member scheduled for less than this amount will be flagged ⚠️ in the roster.<br><br>

<b>Step 7 — Download Results</b><br>
Scroll to the bottom of the page and click the <b>💾 Save Finished Schedule</b> button to download the generated schedule. The file will go to your downloads folder.<br><br>

<b>Step 8 — Match Hosts to Guests (optional)</b><br>
If you need to pair recruit lane hosts with visiting guests by location, scroll to the bottom and open the <b>🤝 Optional: Match Hosts to Guests by Location</b> section. See the detailed instructions there.<br><br>

<b>Format reminder:</b> Column A = staff name, Column B = their availability (e.g. <i>8am-4pm</i> or <i>Available all day!</i>). No headers needed.
</div>
""", unsafe_allow_html=True)

# CHANGED: Template download moved here from inside the expander so it sits
# right after Step 4 where the instructions reference it.
st.download_button("📥 Download Excel Template", generate_template(), "OSU_Football_Template.xlsx")

st.divider()

# --- 2. CORE SCHEDULING LOGIC ---

# FIXED: fmt_time moved here, outside all loops.
# Before, it was redefined every iteration of the while loop below — wasteful and error-prone.
# Now it's defined once and reused anywhere in the file, just like a static helper method in Java.
def fmt_time(minutes):
    h, m = minutes // 60, minutes % 60
    suffix = "AM" if h < 12 else "PM"
    display_h = h if h <= 12 else h - 12
    if display_h == 0: display_h = 12
    return f"{display_h}:{m:02d} {suffix}"

def parse_time(t_str):
    if not t_str or pd.isna(t_str): return None
    t_str = str(t_str).strip().upper().replace('.', '')
    if any(x in t_str for x in ["EOD", "END", "4PM", "4:00PM"]):
        return time(16, 0)
    for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M", "%H"):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            # Fine to keep bare here — we're intentionally trying multiple formats one by one.
            continue
    # FIXED: log when no format matched so you know which string was unparseable.
    # Before, this silently returned None with no indication of what went wrong.
    print(f"[parse_time] could not parse: '{t_str}'")
    return None

def time_to_min(t):
    return t.hour * 60 + t.minute

def get_availability_minutes(avail_string, start_m, end_m):
    if pd.isna(avail_string): return set()
    str_val = str(avail_string).strip().lower()

    if str_val in ["available all day!", "available all day", "all day"]:
        return set(range(start_m, end_m))

    if "not available" in str_val:
        return set()

    minutes = set()
    text = str_val.replace(';', '|').replace('and', '|').replace(',', '|')
    for seg in text.split('|'):
        if '-' in seg:
            try:
                parts = seg.split('-')
                start_t = parse_time(parts[0].strip())
                end_raw = parts[1].split('(')[0].strip()
                end_t = parse_time(end_raw)
                if start_t and end_t:
                    s, e = time_to_min(start_t), time_to_min(end_t)
                    s_clip = max(start_m, s)
                    e_clip = min(end_m, e)
                    if e_clip > s_clip:
                        for m in range(s_clip, e_clip): minutes.add(m)
            except Exception as e:
                # FIXED: was bare 'except: continue' — now logs which segment failed.
                # Check your terminal output when running locally to see these messages.
                print(f"[parse error in get_availability_minutes] segment='{seg}' error={e}")
                continue
    return minutes

def build_lane_sticky(primary_pool, secondary_pool, start_min, end_min, min_minutes):
    lane_schedule = []
    curr = start_min
    last_person = None

    while curr < end_min:
        best_person = None
        target_pool = None

        for pool in [primary_pool, secondary_pool]:
            if last_person in pool and curr in pool[last_person]:
                stretch = 0
                for m in range(curr, end_min):
                    if m in pool[last_person]: stretch += 1
                    else: break
                if stretch >= min_minutes:
                    best_person = last_person
                    target_pool = pool
                    break

        if not best_person:
            longest_stretch = -1
            for pool in [primary_pool, secondary_pool]:
                for name, mins in pool.items():
                    if curr in mins:
                        stretch = 0
                        for m in range(curr, end_min):
                            if m in mins: stretch += 1
                            else: break
                        if stretch >= min_minutes and stretch > longest_stretch:
                            longest_stretch = stretch
                            best_person = name
                            target_pool = pool
                if best_person: break

        if best_person:
            stretch = 0
            for m in range(curr, end_min):
                if m in target_pool[best_person]: stretch += 1
                else: break
            seg_end = curr + stretch
            lane_schedule.append({'name': best_person, 'start': curr, 'end': seg_end})
            for m in range(curr, seg_end):
                target_pool[best_person].discard(m)
            last_person = best_person
            curr = seg_end
        else:
            lane_schedule.append({'name': 'GAP', 'start': curr, 'end': curr + 1})
            last_person = None
            curr += 1

    return lane_schedule

def format_cell(lane_data, b_start_str, b_end_str):
    s_m, e_m = time_to_min(parse_time(b_start_str)), time_to_min(parse_time(b_end_str))

    relevant_segs = []
    for seg in lane_data:
        overlap_s, overlap_e = max(s_m, seg['start']), min(e_m, seg['end'])
        if overlap_s < overlap_e:
            relevant_segs.append({'name': seg['name'], 'start': overlap_s, 'end': overlap_e})

    if not relevant_segs:
        return "⚠️ GAP"

    merged = []
    if relevant_segs:
        curr_seg = relevant_segs[0].copy()
        for next_seg in relevant_segs[1:]:
            if next_seg['name'] == curr_seg['name'] and next_seg['start'] == curr_seg['end']:
                curr_seg['end'] = next_seg['end']
            else:
                merged.append(curr_seg)
                curr_seg = next_seg.copy()
        merged.append(curr_seg)

    entries = []
    for m in merged:
        h1, m1 = (m['start'] // 60), (m['start'] % 60)
        h2, m2 = (m['end'] // 60), (m['end'] % 60)
        t1 = f"{(h1-1)%12+1}:{m1:02d}"
        t2 = f"{(h2-1)%12+1}:{m2:02d}"
        entries.append(f"{m['name']} ({t1}-{t2})")

    return " / ".join(entries)

def style_gaps(val):
    color = '#ff4b4b33' if isinstance(val, str) and "⚠️ GAP" in val else ''
    return f'background-color: {color}'

# --- 4. MAIN PAGE SETTINGS (EXPANDABLE) ---
# CHANGED: Template download removed from here — it now lives above with the instructions.
# Remaining sections renumbered 1–4.
with st.expander("⚙️ SETTINGS & CONTROLS (Click to expand)"):
    st.subheader("🔑 1. Priority Staff")
    priority_input = st.text_area("Full names (comma separated):",
        "Trenton Wells, Madison Herbert, Joaquin Lira, Elisabeth Christina Kearney, Kai Switzer, Reagan Butler, Emma Sherman")
    PRIORITY_NAMES = [p.strip() for p in priority_input.split(",") if p.strip()]

    st.divider()
    st.subheader("🏟️ 2. Lane Counts")
    num_col1, num_col2 = st.columns(2)
    with num_col1:
        num_recruit = st.number_input("Recruit Lanes:", value=8)
    with num_col2:
        num_floater = st.number_input("Floater Lanes:", value=5)

    st.divider()
    st.subheader("⏰ 3. Practice Times")
    p_col1, p_col2 = st.columns(2)
    with p_col1:
        practice_start = st.time_input("Practice Start Time:", value=time(6, 0))
    with p_col2:
        practice_end = st.time_input("Practice End Time:", value=time(16, 0))

    st.divider()
    st.subheader("⚖️ 4. Hour Constraints")
    min_hours = st.number_input("Minimum Hours per Staff Member:", value=2.0, step=0.5)

st.write("")

# --- 5. MAIN PROCESSING ---
file = st.file_uploader("📂 Upload Today's Practice Availability (.xlsx)", type="xlsx")

if file:
    # FIXED: header=None tells pandas not to treat row 1 as column names.
    # Without this, the first staff member's name gets eaten as a column label and lost.
    # Columns are now referenced by integer index (0, 1) instead of string names.
    raw_df = pd.read_excel(file, header=None)
    df = raw_df.dropna(subset=[0])  # drop rows where column A (index 0) is empty

    start_m = time_to_min(practice_start)
    end_m = time_to_min(practice_end)
    min_m = int(min_hours * 60)

    p_pool, o_pool = {}, {}
    warnings = []

    for _, row in df.iterrows():
        name = str(row.iloc[0]).strip()
        avail_str = str(row.iloc[1])

        text = avail_str.strip().lower().replace(';', '|').replace('and', '|').replace(',', '|')
        for seg in text.split('|'):
            if '-' in seg:
                try:
                    parts = seg.split('-')
                    end_raw = parts[1].split('(')[0].strip()
                    end_t = parse_time(end_raw)
                    if end_t and time_to_min(end_t) > end_m:
                        warnings.append(f"🔍 **{name}** listed availability until {end_raw.upper()}, which exceeds practice end time.")
                except Exception as e:
                    # FIXED: was bare 'except: continue' — now logs name and segment so you
                    # know exactly which row in the uploaded file caused the issue.
                    print(f"[parse error in warnings check] name='{name}' segment='{seg}' error={e}")
                    continue

        mins = get_availability_minutes(avail_str, start_m, end_m)
        if any(pn.lower() in name.lower() for pn in PRIORITY_NAMES):
            p_pool[name] = mins
        else:
            o_pool[name] = mins

    if warnings:
        with st.container():
            st.warning("⚠️ **Data Validation Alerts:** Possible typos found in the uploaded file.")
            for w in warnings:
                st.write(w)

    all_lanes = []
    for i in range(num_recruit):
        all_lanes.append({"type": f"Recruit Lane {i+1}", "data": build_lane_sticky(o_pool, p_pool, start_m, end_m, min_m)})
    for i in range(num_floater):
        all_lanes.append({"type": f"Floater Lane {i+1}", "data": build_lane_sticky(p_pool, o_pool, start_m, end_m, min_m)})

    # NEW: collect only the first scheduled host in each Recruit Lane.
    # These are the only people who get paired with guests — floater lanes are excluded.
    # "First host" = the first non-GAP segment in the lane's schedule data.
    recruit_lane_first_hosts = set()
    for lane in all_lanes:
        if not lane["type"].startswith("Recruit Lane"):
            continue  # skip floater lanes entirely
        for seg in lane["data"]:
            if seg["name"] != "GAP":
                recruit_lane_first_hosts.add(seg["name"])
                break  # only want the first person, then move to next lane

    # FIXED: fmt_time is now defined at the top of the file, not re-created here every loop.
    # The while loop is now clean — it just calls fmt_time, not defines it.
    BLOCKS = []
    curr = start_m
    while curr < end_m:
        nxt = min(curr + 120, end_m)
        BLOCKS.append((fmt_time(curr), fmt_time(nxt)))
        curr = nxt

    rows, staff_summary = [], {}

    for lane in all_lanes:
        r = {"Lane": lane['type']}
        for b_s, b_e in BLOCKS:
            r[f"{b_s}-{b_e}"] = format_cell(lane['data'], b_s, b_e)
        rows.append(r)

        for seg in lane['data']:
            if seg['name'] != 'GAP':
                name = seg['name']
                duration = (seg['end'] - seg['start']) / 60
                if name not in staff_summary:
                    staff_summary[name] = {"Total Hours": 0, "Lanes": set()}
                staff_summary[name]["Total Hours"] += duration
                staff_summary[name]["Lanes"].add(lane['type'])

    st.subheader("🏈 Generated Practice Grid")
    st.dataframe(pd.DataFrame(rows).style.map(style_gaps), use_container_width=True)

    st.divider()
    st.subheader("📋 Master Staffing Roster")
    st.write("Complete list of staff assignments:")

    roster_data = []
    for name, info in staff_summary.items():
        total_hrs = round(info["Total Hours"], 2)
        status = "⚠️ Under Minimum" if total_hrs < min_hours else ""
        roster_data.append({
            "Staff Member": name,
            "Total Hours": total_hrs,
            "Status": status,
            "Assigned Lanes": ", ".join(sorted(list(info["Lanes"])))
        })

    if roster_data:
        roster_df = pd.DataFrame(roster_data).sort_values("Staff Member")
        st.table(roster_df)

        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            pd.DataFrame(rows).to_excel(writer, index=False, sheet_name='Schedule')
            roster_df.to_excel(writer, index=False, sheet_name='Staff_Roster')
        st.download_button("💾 Save Finished Schedule", out.getvalue(), "OSU_Football_Report.xlsx")

        # --- NEW: OPTIONAL GUEST MATCHING SECTION ---
        # This only appears after a schedule has been generated.
        # It's wrapped in an expander so it's out of the way when not needed.
        st.divider()
        st.markdown("### 🤝 Optional: Host & Guest Matching")
        st.markdown("""
<div class="instruction-box">
This feature pairs the <b>first scheduled host in each Recruit Lane</b> with a visiting guest based on geographic proximity.
Floater lane staff are not included. You will need two files ready before using this:<br><br>

<b>What you need:</b><br>
&nbsp;&nbsp;• <b>Staff Roster Excel</b> — the main staff roster file with columns: First Name, Last Name, Hometown.<br>
&nbsp;&nbsp;• <b>Guest List PDF</b> — the recruit visit PDF with guest name and city (state) columns.<br><br>

<b>How matching works:</b><br>
&nbsp;&nbsp;1. The app first tries to match each host with a guest from the <b>same city</b>.<br>
&nbsp;&nbsp;2. If no city match exists, it tries the <b>same state</b>.<br>
&nbsp;&nbsp;3. If no state match, it tries the <b>same region</b> (Northeast, Southeast, Midwest, Southwest, West).<br>
&nbsp;&nbsp;4. Any remaining unmatched hosts are paired with whoever is left.<br><br>

<b>How to use it:</b><br>
&nbsp;&nbsp;1. Upload both files using the uploaders inside the expander below.<br>
&nbsp;&nbsp;2. The match table will generate automatically.<br>
&nbsp;&nbsp;3. Review the <b>Match Quality</b> column to see how well each pair was matched.<br>
&nbsp;&nbsp;4. Click <b>💾 Download Host-Guest Matches</b> to save the results to Excel.
</div>
""", unsafe_allow_html=True)

        with st.expander("🤝 Optional: Match Hosts to Guests by Location (Click to expand)"):

            roster_file = st.file_uploader("📋 Upload Staff Roster Excel (with hometowns)", type="xlsx", key="roster")
            guest_pdf   = st.file_uploader("📄 Upload Guest List PDF", type="pdf", key="guests")

            if roster_file and guest_pdf:
                # FIXED: header=0 because the staff roster has a real header row
                # (First Name, Last Name, Hometown). Previously using header=None
                # treated that header row as a person named "First Name Last Name"
                # and shifted all real staff rows down by one, causing missed matches.
                staff_roster_df = pd.read_excel(roster_file, header=0)

                # Extract guests from the PDF using pdfplumber
                guest_list = extract_guests_from_pdf(guest_pdf)

                if not guest_list:
                    st.warning("⚠️ Could not read any guests from the PDF. Make sure it's a digital (not scanned) PDF with a visible table.")
                else:
                    # CHANGED: only pass the first host from each Recruit Lane.
                    # Floater lane staff and anyone after the first host in a lane
                    # are excluded — they don't get guest assignments.
                    match_df = match_hosts_to_guests(recruit_lane_first_hosts, staff_roster_df, guest_list)

                    if match_df.empty:
                        st.warning("No matches could be made. Check that staff names in the roster match names in the schedule.")
                    else:
                        st.success(f"✅ Matched {len(match_df)} hosts to guests.")
                        st.dataframe(match_df, use_container_width=True)

                        # Download the match results as Excel
                        match_out = io.BytesIO()
                        with pd.ExcelWriter(match_out, engine='openpyxl') as writer:
                            match_df.to_excel(writer, index=False, sheet_name='Host_Guest_Matches')
                        st.download_button(
                            "💾 Download Host-Guest Matches",
                            match_out.getvalue(),
                            "OSU_Host_Guest_Matches.xlsx"
                        )

                        # Show a summary of how many matched at each tier
                        st.markdown("**Match Quality Summary:**")
                        summary = match_df["Match Quality"].value_counts().reset_index()
                        summary.columns = ["Match Quality", "Count"]
                        st.table(summary)
    else:
        st.warning("No staff members could be scheduled. Check the availability format in your upload.")