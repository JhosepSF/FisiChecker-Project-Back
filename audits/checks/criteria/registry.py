# audits/checks/criteria/registry.py
from typing import Dict, Callable, List
from .base import CriterionOutcome, CheckMode

# ————————————————————————————————————————————————————————————
# Principio 1 — Perceptible (1.x)
# ————————————————————————————————————————————————————————————
from .p1.c_1_1_1_alt_text import run_1_1_1

from .p1.c_1_2_1_time_based_alt import run_1_2_1
from .p1.c_1_2_2_captions_prerecorded import run_1_2_2
from .p1.c_1_2_3_ad_or_media_alt_prerecorded import run_1_2_3
from .p1.c_1_2_4_captions_live import run_1_2_4
from .p1.c_1_2_5_audio_description_prerecorded import run_1_2_5
from .p1.c_1_2_6_sign_language_prerecorded import run_1_2_6
from .p1.c_1_2_7_extended_ad_prerecorded import run_1_2_7
from .p1.c_1_2_8_media_alt_prerecorded import run_1_2_8
from .p1.c_1_2_9_audio_only_live import run_1_2_9

from .p1.c_1_3_1_info_and_relationships import run_1_3_1
from .p1.c_1_3_2_meaningful_sequence import run_1_3_2
from .p1.c_1_3_3_sensory_characteristics import run_1_3_3
from .p1.c_1_3_4_orientation import run_1_3_4
from .p1.c_1_3_5_identify_input_purpose import run_1_3_5
from .p1.c_1_3_6_identify_purpose import run_1_3_6

from .p1.c_1_4_1_use_of_color import run_1_4_1
from .p1.c_1_4_2_audio_control import run_1_4_2
from .p1.c_1_4_3_contrast_minimum import run_1_4_3
from .p1.c_1_4_4_resize_text import run_1_4_4
from .p1.c_1_4_5_images_of_text import run_1_4_5
from .p1.c_1_4_6_contrast_enhanced import run_1_4_6
from .p1.c_1_4_7_low_or_no_bg_audio import run_1_4_7
from .p1.c_1_4_8_visual_presentation import run_1_4_8
from .p1.c_1_4_9_images_of_text_no_exception import run_1_4_9
from .p1.c_1_4_10_reflow import run_1_4_10
from .p1.c_1_4_11_non_text_contrast import run_1_4_11
from .p1.c_1_4_12_text_spacing import run_1_4_12
from .p1.c_1_4_13_content_on_hover_or_focus import run_1_4_13

# ————————————————————————————————————————————————————————————
# Principio 2 — Operable (2.x)
# ————————————————————————————————————————————————————————————
from .p2.c_2_1_1_keyboard import run_2_1_1
from .p2.c_2_1_2_no_keyboard_trap import run_2_1_2
from .p2.c_2_1_3_keyboard_no_exception import run_2_1_3
from .p2.c_2_1_4_character_key_shortcuts import run_2_1_4

from .p2.c_2_2_1_timing_adjustable import run_2_2_1
from .p2.c_2_2_2_pause_stop_hide import run_2_2_2
from .p2.c_2_2_3_no_timing import run_2_2_3
from .p2.c_2_2_4_interruptions import run_2_2_4
from .p2.c_2_2_5_re_authenticating import run_2_2_5
from .p2.c_2_2_6_timeouts import run_2_2_6

from .p2.c_2_3_1_three_flashes_below_threshold import run_2_3_1
from .p2.c_2_3_2_three_flashes import run_2_3_2
from .p2.c_2_3_3_animation_from_interactions import run_2_3_3

from .p2.c_2_4_1_bypass_blocks import run_2_4_1
from .p2.c_2_4_2_page_titled import run_2_4_2
from .p2.c_2_4_3_focus_order import run_2_4_3
from .p2.c_2_4_4_link_purpose_in_context import run_2_4_4
from .p2.c_2_4_5_multiple_ways import run_2_4_5
from .p2.c_2_4_6_headings_labels import run_2_4_6
from .p2.c_2_4_7_focus_visible import run_2_4_7
from .p2.c_2_4_8_location import run_2_4_8
from .p2.c_2_4_9_link_purpose_link_only import run_2_4_9
from .p2.c_2_4_10_section_headings import run_2_4_10

from .p2.c_2_5_1_pointer_gestures import run_2_5_1
from .p2.c_2_5_2_pointer_cancellation import run_2_5_2
from .p2.c_2_5_3_label_in_name import run_2_5_3
from .p2.c_2_5_4_motion_actuation import run_2_5_4
from .p2.c_2_5_5_target_size import run_2_5_5
from .p2.c_2_5_6_concurrent_input_mechanisms import run_2_5_6

# ————————————————————————————————————————————————————————————
# Principio 3 — Comprensible (3.x)
# ————————————————————————————————————————————————————————————
from .p3.c_3_1_1_language_of_page import run_3_1_1
from .p3.c_3_1_2_language_of_parts import run_3_1_2
from .p3.c_3_1_3_unusual_words import run_3_1_3
from .p3.c_3_1_4_abbreviations import run_3_1_4
from .p3.c_3_1_5_reading_level import run_3_1_5
from .p3.c_3_1_6_pronunciation import run_3_1_6

from .p3.c_3_2_1_on_focus import run_3_2_1
from .p3.c_3_2_2_on_input import run_3_2_2
from .p3.c_3_2_3_consistent_navigation import run_3_2_3
from .p3.c_3_2_4_consistent_identification import run_3_2_4
from .p3.c_3_2_5_change_on_request import run_3_2_5

from .p3.c_3_3_1_error_identification import run_3_3_1
from .p3.c_3_3_2_labels_or_instructions import run_3_3_2
from .p3.c_3_3_3_error_suggestion import run_3_3_3
from .p3.c_3_3_4_error_prevention_legal import run_3_3_4
from .p3.c_3_3_5_help import run_3_3_5
from .p3.c_3_3_6_error_prevention_all import run_3_3_6
# (Si implementas 3.3.7, impórtalo aquí)

# ————————————————————————————————————————————————————————————
# Principio 4 — Robusto (4.x)
# ————————————————————————————————————————————————————————————
from .p4.c_4_1_1_parsing import run_4_1_1
from .p4.c_4_1_2_name_role_value import run_4_1_2
from .p4.c_4_1_3_status_messages import run_4_1_3

# Firma común
CheckFn = Callable[..., CriterionOutcome]

REGISTRY: Dict[str, CheckFn]= {
    # P1
    "1.1.1":run_1_1_1,
    "1.2.1":run_1_2_1,
    "1.2.2":run_1_2_2,
    "1.2.3":run_1_2_3,
    "1.2.4":run_1_2_4,
    "1.2.5":run_1_2_5,
    "1.2.6":run_1_2_6,
    "1.2.7":run_1_2_7,
    "1.2.8":run_1_2_8,
    "1.2.9":run_1_2_9,
    "1.3.1":run_1_3_1,
    "1.3.2":run_1_3_2,
    "1.3.3":run_1_3_3,
    "1.3.4":run_1_3_4,
    "1.3.5":run_1_3_5,
    "1.3.6":run_1_3_6,
    "1.4.1":run_1_4_1,
    "1.4.2":run_1_4_2,
    "1.4.3":run_1_4_3,
    "1.4.4":run_1_4_4,
    "1.4.5":run_1_4_5,
    "1.4.6":run_1_4_6,
    "1.4.7":run_1_4_7,
    "1.4.8":run_1_4_8,
    "1.4.9":run_1_4_9,
    "1.4.10":run_1_4_10,
    "1.4.11":run_1_4_11,
    "1.4.12":run_1_4_12,
    "1.4.13":run_1_4_13,
    # P2
    "2.1.1":run_2_1_1,
    "2.1.2":run_2_1_2,
    "2.1.3":run_2_1_3,
    "2.1.4":run_2_1_4,
    "2.2.1":run_2_2_1,
    "2.2.2":run_2_2_2,
    "2.2.3":run_2_2_3,
    "2.2.4":run_2_2_4,
    "2.2.5":run_2_2_5,
    "2.2.6":run_2_2_6,
    "2.3.1":run_2_3_1,
    "2.3.2":run_2_3_2,
    "2.3.3":run_2_3_3,
    "2.4.1":run_2_4_1,
    "2.4.2":run_2_4_2,
    "2.4.3":run_2_4_3,
    "2.4.4":run_2_4_4,
    "2.4.5":run_2_4_5,
    "2.4.6":run_2_4_6,
    "2.4.7":run_2_4_7,
    "2.4.8":run_2_4_8,
    "2.4.9":run_2_4_9,
    "2.4.10":run_2_4_10,
    "2.5.1":run_2_5_1,
    "2.5.2":run_2_5_2,
    "2.5.3":run_2_5_3,
    "2.5.4":run_2_5_4,
    "2.5.5":run_2_5_5,
    "2.5.6":run_2_5_6,
    # P3
    "3.1.1":run_3_1_1,
    "3.1.2":run_3_1_2,
    "3.1.3":run_3_1_3,
    "3.1.4":run_3_1_4,
    "3.1.5":run_3_1_5,
    "3.1.6":run_3_1_6,
    "3.2.1":run_3_2_1,
    "3.2.2":run_3_2_2,
    "3.2.3":run_3_2_3,
    "3.2.4":run_3_2_4,
    "3.2.5":run_3_2_5,
    "3.3.1":run_3_3_1,
    "3.3.2":run_3_3_2,
    "3.3.3":run_3_3_3,
    "3.3.4":run_3_3_4,
    "3.3.5":run_3_3_5,
    "3.3.6":run_3_3_6,
    # P4
    "4.1.1":run_4_1_1,
    "4.1.2":run_4_1_2,
    "4.1.3":run_4_1_3,
}

def get_check(code: str) -> CheckFn:
    fn = REGISTRY.get(code)
    if not fn:
        raise ValueError(f"No hay función registrada para el criterio {code}")
    return fn

def list_available_codes() -> List[str]:
    """
    Devuelve la lista de códigos registrados: ["1.1.1", "1.2.1", ...]
    """
    return list(REGISTRY.keys())
