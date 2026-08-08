"""
Massive Messing-Zahnräder in Blender.

Erzeugt aus einer Liste von Zahnrad-Definitionen (Position, Radius, Drehachse,
Drehrichtung, Geschwindigkeit) massive, gefaste Messing-Zahnräder inklusive
Dauerrotation. Die Zähnezahl wird über ein einheitliches Modul skaliert,
damit alle Zahnräder geometrisch perfekt ineinandergreifen.

Ausführen: Blender -> Scripting-Tab -> dieses Skript laden -> Run Script
(oder headless: blender --background --python build_brass_gears.py)
"""

import json
import math
import os
import random

import bmesh
import bpy
import mathutils

# ============================================================
# KONFIGURATION - hier lässt sich das Ergebnis anpassen
# ============================================================

DEV_MODE_NO_TEETH = False  # True = Performance-Modus (nur glatte Zylinder), False = Volle Zähne

# Falls eine JSON-Datei mit demselben Schema neben diesem Skript liegt, wird
# sie automatisch geladen. Sonst greift die eingebettete GEAR_DATA weiter unten.
JSON_FILENAME = "projekt.json"

SCALE = 4.0  # Welt-Größenfaktor - macht aus den kleinen Radien "massive" Räder
GEAR_THICKNESS_RATIO = 0.35  # Dicke eines Rads relativ zu seinem Kopfkreis-Radius
TEETH_PER_UNIT_RADIUS = 10  # Automatische Zähnezahl (Radius * Faktor), da nicht vorgegeben
MIN_TEETH = 6  # Untergrenze, damit auch sehr kleine Räder noch wie Zahnräder aussehen
BEVEL_WIDTH = 0.025  # Kantenverrundung für den "poliert/gefertigt"-Look
BASE_ANGULAR_SPEED = math.radians(45)  # Grad/Sekunde bei speed = 1.0
CYCLE_FRAMES = 250  # Über diese Framespanne läuft die (endlos fortgesetzte) Animation
GEAR_MODULE = 0.45  # Fester Modulwert für alle Zahnräder – garantiert perfektes Ineinandergreifen!
COLLECTION_NAME = "Messingzahnraeder"
MATERIAL_NAME = "Messing"
STEEL_MATERIAL_NAME = "Stahl_Zahnraeder"
AXLE_STEEL_MATERIAL_NAME = "Stahl_Achsen"
AXIS_MATERIAL_NAME = "Transparente_Hohlachse"

# --- Echte Evolventenverzahnung (statt grobem Trapez-Platzhalter) ---
# Damit greifen die Zähne geometrisch tatsächlich korrekt ineinander:
# Der Wälzkreis (r_pitch) zweier kämmender Räder berührt sich exakt (Mittenabstand =
# Summe der Wälzkreisradien), der Zahnkopf (r_addendum) reicht dabei in den Zahnfuß
# (r_dedendum) des Gegenrads hinein, ohne diesen zu berühren (Kopfspiel).
PRESSURE_ANGLE = math.radians(20.0)  # Standard-Eingriffswinkel im Maschinenbau
ADDENDUM_COEFF = 1.0  # Zahnkopfhöhe = 1.0 * Modul
DEDENDUM_COEFF = 1.25  # Zahnfußhöhe = 1.25 * Modul (0.25*Modul Kopfspiel)
INVOLUTE_SEGMENTS = 6  # Stützpunkte pro Zahnflanke (Glätte der Evolvente)

# --- Zifferblatt + Sonnenzeiger (Lübecker-Uhr-Stil) ---
# Falls diese Bilddatei neben dem Skript liegt, wird sie als Zifferblatt-Textur
# verwendet; sonst wird ersatzweise ein einfarbiges dunkelblaues Zifferblatt erzeugt.
DIAL_IMAGE_FILENAME = "zifferring.png"
DIAL_MATERIAL_NAME = "Zifferblatt_Material"

# Drehrichtung/-geschwindigkeit der Hohlwelle, auf der Rad 6 (+ Rad 5) sitzen.
# Der Sonnenzeiger wird bewusst über dieselben Konstanten angetrieben, damit er
# IMMER exakt synchron zu dieser Achse läuft, auch wenn die Werte später geändert werden.
SHAFT_56_DIR = -1
SHAFT_56_SPEED = 1

# Drehrichtung/-geschwindigkeit der (eigenen, massiven) Welle von Rad 10 - der
# Mondzeiger wird bewusst über dieselben Konstanten angetrieben, damit er IMMER
# exakt synchron zu diesem (hintersten) Rad läuft.
SHAFT_10_DIR = -1
# WICHTIG: bewusst ungleich SHAFT_56_SPEED gewählt. Die Mondphase entsteht aus der
# DIFFERENZ zwischen der Mondzeiger-Wellendrehzahl (hier) und der Sonnenzeiger-
# Wellendrehzahl (SHAFT_56_SPEED) - sind beide gleich, gäbe es keine sichtbare
# Planetenbewegung (siehe build_moon_capsule_object).
SHAFT_10_SPEED = 1.6

MOON_MATERIAL_NAME = "Mondkugel_Schwarzlack"
GEGENGEWICHT_MATERIAL_NAME = "Zeiger_Gegengewicht_Blau"

# --- Planetengetriebe an der Mondzeiger-Spitze (siehe "Getriebe.jpg") ---
# Kleines, separates Modul für die beiden filigranen 24-zähnigen Getrieberäder
# (Zentralrad auf der Sonnenzeiger-Welle + Rad auf der Mondkugelwelle) - viel
# kleiner als GEAR_MODULE, da diese Räder nur Dekoration/Detail sind, nicht Teil
# der tragenden Hauptgetriebe-Kette.
MOON_GEAR_MODULE = 0.075
MOON_GEAR_TEETH = 24  # historisch: an der Stralsunder Nikolaikirche je 24 Zähne

# NEU: Statt eines festen Moduls wird der Modul jetzt aus einem Zielradius
# abgeleitet (siehe module_for_addendum()) - das macht die Räder unabhängig
# von der jeweiligen Mondkugelgröße immer passend groß. Versuchswert: halber
# Mondkugelradius (kann pro moon_hand-Eintrag über "gear_radius_ratio"
# überschrieben werden).
MOON_GEAR_RADIUS_RATIO = 0.5

# Abstand (in denselben unskalierten Einheiten wie z.B. ball_radius), um den
# das Differenzialgetriebe über die Basis-Höhe des Mondzeigers angehoben wird -
# damit es sicher VOR dem Zifferblatt liegt und nicht mit dem duennen Rohr des
# Sonnenzeigers kollidiert (kann pro Eintrag über "gear_z_offset" angepasst
# werden).
MOON_GEAR_Z_OFFSET = 0.4

# --- Sternscheibe (Astrolabium) mit "schwerkraftgefuehrten" Tierkreisfiguren ---
# Die Scheibe selbst dreht sich einmal pro (siderischem) Tag; die goldenen
# Tierkreis-Figuren darauf sind NICHT starr mit ihr verbunden, sondern per
# Gegengewicht drehbar gelagert, sodass sie durch die Schwerkraft immer
# aufrecht bleiben (siehe build_zodiac_figure_object fuer die Umsetzung).
STAR_DISC_DIR = -1
STAR_DISC_SPEED = 0.3  # deutlich langsamer als die "aktiven" Zeiger, gut sichtbar
STAR_DISC_MATERIAL_NAME = "Sternscheibe_Blau"

# Ordnet den JSON-Feldwert "axis" auf eine statische Vorab-Rotation ab, damit
# die lokale Z-Achse (= Extrusionsrichtung der Zahnrad-Silhouette) danach in
# die gewünschte Welt-Achse zeigt. Die eigentliche Dreh-Animation läuft dann
# immer um die lokale Z-Achse (siehe animate_spin).
AXIS_ALIGN_EULER = {
    "x": (0.0, math.radians(90.0), 0.0),
    "y": (math.radians(-90.0), 0.0, 0.0),
    "z": (0.0, 0.0, 0.0),
}

# Eingebettete Fallback-Daten (Inhalt der hochgeladenen projekt.json), falls
# keine externe Datei gefunden wird.
GEAR_DATA = [
    # --- Zentraler "Turm" (koaxial: 10 -> 7 -> 6/5 -> 2, alle bei x=0,y=0) ---
    # Rad 10: sitzt auf der innersten, massiven Welle (eigene Welle).
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 0, "dir": SHAFT_10_DIR, "speed": SHAFT_10_SPEED, "axis": "z",
     "id": 10, "teeth": 64, "thickness": 0.25, "spoked": True},
    # Rad 7: eigenständige, einfache Welle (nicht Teil der Hohlwellen-Verschachtelung), kämmt mit 8.
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 1, "dir": SHAFT_10_DIR, "speed": SHAFT_10_SPEED, "axis": "z",
     "id": 7, "teeth": 64, "thickness": 0.25, "spoked": True},
    # Rad 6 + Rad 5: gemeinsame Hohlwelle, die die Welle von Rad 10 umhüllt.
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 2, "dir": SHAFT_56_DIR, "speed": SHAFT_56_SPEED, "axis": "z",
     "id": 6, "teeth": 80, "thickness": 0.25, "spoked": True},
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 3, "dir": SHAFT_56_DIR, "speed": SHAFT_56_SPEED, "axis": "z",
     "id": 5, "teeth": 80, "thickness": 0.25, "spoked": True},
    # Rad 2: eigene (weitere/äußere) Hohlwelle, umhüllt die Hohlwelle von 6/5.
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 4, "dir": SHAFT_56_DIR, "speed": SHAFT_56_SPEED, "axis": "z",
     "id": 2, "teeth": 80, "thickness": 0.25, "spoked": True},

    # --- Parallelwelle A: 9 (kämmt mit 10) + 8 (gemeinsame Welle mit 9, kämmt mit 7) ---
    # y-Abstand = (r_pitch(16) + r_pitch(64)) / SCALE = (3.6 + 14.4) / 4 = 4.5
    {"type": "gear", "group": None, "x": 0, "y": -4.5, "z": 0, "dir": -SHAFT_10_DIR, "speed": SHAFT_10_SPEED * 4,
     "axis": "z", "id": 9, "teeth": 16, "thickness": 0.25},
    {"type": "gear", "group": None, "x": 0, "y": -4.5, "z": 1, "dir": -SHAFT_10_DIR, "speed": SHAFT_10_SPEED * 4,
     "axis": "z", "id": 8, "teeth": 16, "thickness": 0.25},

    # --- Parallelwelle B: 4 (kämmt mit 5) + 3 (gemeinsame Welle mit 4, kämmt mit 2) ---
    # y-Abstand = (r_pitch(16) + r_pitch(80)) / SCALE = (3.6 + 18.0) / 4 = 5.4
    {"type": "gear", "group": None, "x": 0, "y": -5.4, "z": 3, "dir": -SHAFT_56_DIR, "speed": SHAFT_56_SPEED * 5,
     "axis": "z", "id": 4, "teeth": 16, "thickness": 0.25},
    {"type": "gear", "group": None, "x": 0, "y": -5.4, "z": 4, "dir": -SHAFT_56_DIR, "speed": SHAFT_56_SPEED * 5,
     "axis": "z", "id": 3, "teeth": 16, "thickness": 0.25},

    # --- Sichtbare (teil-transparente) Hohlwellen-Objekte fuer den zentralen Turm ---
    # Innerste, massive Welle von Rad 10. (etwas duenner als zuvor, passend
    # zum neuen, filigraneren Mondphasen-Differenzialgetriebe)
    {"type": "axis", "x": 0, "y": 0, "z": -0.4, "length": 4.8, "r": 0.10, "hollow": False, "id": "10"},
    # Hohlwelle, die die Welle von Rad 10 umhuellt; traegt Rad 6 + 5.
    {"type": "axis", "x": 0, "y": 0, "z": -0.4, "length": 4.8, "r": 0.25, "wall_thickness": 0.10, "hollow": True,
     "id": "56"},

    # Kleines Zahnrad (15 Zaehne), das mit dem MITTLEREN der drei oberen
    # Kleines Zahnrad (15 Zaehne), das mit dem HINTERSTEN der grossen
    # Zahnraeder (Rad 6, z=2, teilt die 56-Welle mit Rad 5) in Eingriff steht -
    # auf einer eigenen, neuen Welle.
    # y-Abstand exakt aus den Waelzkreisradien berechnet: (18.0+3.375)/4 = 5.34375
    {"type": "gear", "group": None, "x": 0, "y": 5.34375, "z": 2, "dir": -SHAFT_56_DIR,
     "speed": SHAFT_56_SPEED * (80.0 / 15.0), "axis": "z", "id": "abtrieb56", "teeth": 15, "thickness": 0.25},

    # Kurzer, massiver Wellenstummel hinter diesem Rad, der "nach hinten
    # heraus" ragt (gegenueber vom Zifferblatt) - rein dekorativ, deutet die
    # Antriebswelle dieses Abtriebsrads an.
    {"type": "axis", "x": 0, "y": 5.34375, "z": 1.55, "length": 0.7,
     "r": 0.09, "hollow": False, "id": "abtrieb56_welle"},
    # Aeussere Hohlwelle darueber, umhuellt die Welle von 6/5; traegt Rad 2.
    {"type": "axis", "x": 0, "y": 0, "z": -0.4, "length": 4.8, "r": 0.45, "wall_thickness": 0.15, "hollow": True,
     "id": "2"},

    # --- Zifferblatt + Sonnenzeiger (verdeckt das Räderwerk, wie bei einer echten Uhr) ---
    # Zifferblatt: ruht knapp über Rad 2 (Kopfkreis ~18.45), deckt den ganzen Turm ab.
    {"type": "dial", "id": "zifferblatt", "x": 0, "y": 0, "z": 4.375, "radius": 19.0},
    # Sonnenzeiger: sitzt sichtbar auf dem Zifferblatt, wird aber bewusst über
    # SHAFT_56_DIR/SPEED angetrieben - exakt dieselbe Achse wie Rad 6 (+5).
    {"type": "hand", "id": "sonnenzeiger", "x": 0, "y": 0, "z": 4.5, "axis": "z",
     "dir": SHAFT_56_DIR, "speed": SHAFT_56_SPEED,
     "length": 15.35, "sun_radius": 1.1, "rays": 24, "thickness": 0.4},

    # Mondzeiger: duennes Rohr + zweifarbige (halb gold/halb schwarz) Kugel in
    # schwarzer Metall-Halbkugelfassung. Angetrieben von der eigenen Welle von
    # Rad 10 (dem hintersten Rad, urspruenglich 347 Zaehne).
    {"type": "moon_hand", "id": "mondzeiger", "x": 0, "y": 0, "z": 4.55, "axis": "z",
     "dir": SHAFT_10_DIR, "speed": SHAFT_10_SPEED,
     "length": 14.5, "ball_radius": 1.1, "rod_thickness": 0.35},

    # Kleines, sichtbares "Zentralrad" auf der Sonnenzeiger-Welle wurde wieder
    # entfernt (nicht originalgetreu genug).

    # Sichtbare gemeinsame Achse fuer Radpaar 3+4 ("vordere Gruppe", dem
    # Zifferblatt zugewandt, z=3..4) - nur die Achse selbst, keine Platine/
    # Strebe/Bodenplatte.
    {"type": "axis", "id": "3_4", "x": 0, "y": -5.4, "z": 2.9, "length": 1.5,
     "r": 0.075, "hollow": False, "steel": True},

    # Sichtbare gemeinsame Achse fuer Radpaar 8+9 ("hintere Gruppe", z=0..1).
    {"type": "axis", "id": "8_9", "x": 0, "y": -4.5, "z": -0.1, "length": 1.5,
     "r": 0.075, "hollow": False, "steel": True},

    # --- Sternscheibe: sitzt knapp unter dem Zifferblatt (zwischen Zifferblatt
    # und den Haupt-Zahnraedern), Radius etwas kleiner als das Zifferblatt,
    # damit der aeussere Ring mit den roemischen Ziffern sichtbar bleibt.
    {"type": "star_disc", "id": "sternscheibe", "x": 0, "y": 0, "z": 4.40,
     "radius": 15.35, "image": "sternhimmel.png"},

    # 12 der 13 Tierkreiszeichen der Luebecker Uhr (Skorpion fehlt hier bewusst
    # - er ist fest in sternhimmel.png aufgemalt und braucht daher keine
    # eigene positionierbare Figur). Positionen wurden vom Nutzer per Hand
    # anhand des Referenzfotos ermittelt. Jede Figur nutzt das mitgelieferte
    # PNG als Textur (keine eigene Modellierung noetig) und ist ein Kind der
    # Sternscheibe mit automatischer Gegenrotation.
    {"type": "zodiac_figure", "id": "widder", "parent_id": "sternscheibe",
     "angle_deg": 61.00, "orbit_radius": 13, "image": "widder.png",
     "x_offset": -1.0, "y_offset": -1.6, "height": 4.5},
    {"type": "zodiac_figure", "id": "stier", "parent_id": "sternscheibe",
     "angle_deg": 87.00, "orbit_radius": 11.2, "image": "stier.png",
     "x_offset": -0.9, "y_offset": -1.0, "height": 8.0},
    {"type": "zodiac_figure", "id": "zwilling", "parent_id": "sternscheibe",
     "angle_deg": 117.00, "orbit_radius": 11.9, "image": "zwilling.png",
     "x_offset": -1.2, "y_offset": -1.5, "height": 5.5},
    {"type": "zodiac_figure", "id": "krebs", "parent_id": "sternscheibe",
     "angle_deg": 142.00, "orbit_radius": 11.1, "image": "krebs.png",
     "x_offset": -1.0, "y_offset": -1.3, "height": 4.6},
    {"type": "zodiac_figure", "id": "loewe", "parent_id": "sternscheibe",
     "angle_deg": 170.00, "orbit_radius": 8.8, "image": "loewe.png",
     "x_offset": -1.0, "y_offset": -1.3, "height": 6.2},
    {"type": "zodiac_figure", "id": "jungfrau", "parent_id": "sternscheibe",
     "angle_deg": 208.00, "orbit_radius": 9, "image": "jungfrau.png",
     "x_offset": -1.0, "y_offset": -1.8, "height": 5.6},
    {"type": "zodiac_figure", "id": "waage", "parent_id": "sternscheibe",
     "angle_deg": 244.00, "orbit_radius": 8, "image": "waage.png",
     "x_offset": -1.0, "y_offset": -1.6, "height": 5.6},
    {"type": "zodiac_figure", "id": "schlangentraeger", "parent_id": "sternscheibe",
     "angle_deg": 290.00, "orbit_radius": 8.5, "image": "schlangentraeger.png",
     "x_offset": -1.2, "y_offset": -1.6, "height": 5.6},
    {"type": "zodiac_figure", "id": "schuetze", "parent_id": "sternscheibe",
     "angle_deg": 315.00, "orbit_radius": 10.5, "image": "schuetze.png",
     "x_offset": -1.2, "y_offset": -1.6, "height": 5.0},
    {"type": "zodiac_figure", "id": "steinbock", "parent_id": "sternscheibe",
     "angle_deg": 340.00, "orbit_radius": 11, "image": "steinbock.png",
     "x_offset": -1.2, "y_offset": -1.4, "height": 5.0},
    {"type": "zodiac_figure", "id": "wassermann", "parent_id": "sternscheibe",
     "angle_deg": 5.00, "orbit_radius": 11, "image": "wassermann.png",
     "x_offset": -1.3, "y_offset": -1.4, "height": 7.0},
    {"type": "zodiac_figure", "id": "fische", "parent_id": "sternscheibe",
     "angle_deg": 37.00, "orbit_radius": 11.5, "image": "fische.png",
     "x_offset": -1.3, "y_offset": -1.4, "height": 7.0},

    # Zentrales "Heiland"-Medaillon (Christus mit Erdkugel, Strahlenkranz) -
    # sitzt exakt im Zentrum der Sternscheibe (orbit_radius=0). Nutzt dieselbe
    # Gegenrotations-Mechanik wie die Tierkreisfiguren, damit es unabhaengig
    # von der Scheibendrehung nie "mitdreht", sondern fest ausgerichtet bleibt
    # (wie im Original).
    {"type": "zodiac_figure", "id": "heiland", "parent_id": "sternscheibe",
     "angle_deg": 0.0, "orbit_radius": 0.0, "image": "heiland.png", "height": 6.14},
]


# ============================================================
# HILFSFUNKTIONEN
# ============================================================

def load_gear_data():
    """Lädt die Zahnrad-Konfiguration aus einer JSON-Datei neben dem Skript,
    fällt sonst auf die eingebettete GEAR_DATA zurück."""
    script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    json_path = os.path.join(script_dir, JSON_FILENAME)
    if os.path.isfile(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return GEAR_DATA


def get_or_create_collection(name):
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def clear_collection(collection):
    """Entfernt nur zuvor von diesem Skript erzeugte Objekte, lässt die restliche Szene unangetastet."""
    for obj in list(collection.objects):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def get_or_create_brass_material():
    if MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[MATERIAL_NAME]

    mat = bpy.data.materials.new(MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.72, 0.52, 0.18, 1.0)
        bsdf.inputs["Metallic"].default_value = 1.0
        bsdf.inputs["Roughness"].default_value = 0.32
        if "Specular IOR Level" in bsdf.inputs:  # Blender 4.x Benennung
            bsdf.inputs["Specular IOR Level"].default_value = 0.6
    return mat


def get_or_create_steel_material():
    """Stahlgraues Material für die Zahnräder des Getriebes (wie auf dem
    Originalfoto - die eigentlichen Räder sind Stahl/Gusseisen, nicht golden;
    golden bleiben nur die sichtbaren Zifferblatt-Elemente wie Zeiger und
    Sternscheiben-Zierrat)."""
    if STEEL_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[STEEL_MATERIAL_NAME]

    mat = bpy.data.materials.new(STEEL_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.42, 0.43, 0.45, 1.0)  # stahlgrau
        bsdf.inputs["Metallic"].default_value = 1.0
        bsdf.inputs["Roughness"].default_value = 0.45  # etwas matter als poliertes Messing
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.5
    return mat


def get_or_create_moon_material():
    """Schwarz lackiertes Material für die verborgene Hälfte der Mondphasenkugel
    - glänzender Lack, kein Metallic, im Kontrast zur goldfarben polierten
    sichtbaren Hälfte."""
    if MOON_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[MOON_MATERIAL_NAME]

    mat = bpy.data.materials.new(MOON_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.008, 0.008, 0.01, 1.0)
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.15  # glänzender Lack
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.6
    return mat


def get_or_create_counterweight_material():
    """Blaue, leicht glänzende Scheibe als Gegengewicht am kurzen Ende der
    Zeiger (Sonnen- wie Mondzeiger) - wie im Original-Vorbild."""
    if GEGENGEWICHT_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[GEGENGEWICHT_MATERIAL_NAME]

    mat = bpy.data.materials.new(GEGENGEWICHT_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.55, 0.76, 0.94, 1.0)
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.3
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.5
    return mat


def get_or_create_transparent_gold_material():
    """Transparentes Gold für den Mondzeigerarm (Kröpfung/Brücke) - lässt die
    darin verlaufende (dunkle) Mondkugel-Welle durchscheinen."""
    name = "Mondzeigerarm_Gold_Transparent"
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.85, 0.65, 0.13, 1.0)
        bsdf.inputs["Metallic"].default_value = 0.9
        bsdf.inputs["Roughness"].default_value = 0.2
        bsdf.inputs["Alpha"].default_value = 0.35
    return mat


def get_or_create_transparent_material():
    if AXIS_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[AXIS_MATERIAL_NAME]

    mat = bpy.data.materials.new(AXIS_MATERIAL_NAME)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'  # Aktiviert Transparenz in Eevee/Cycles
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.9, 1.0)
        bsdf.inputs["Metallic"].default_value = 0.8
        bsdf.inputs["Roughness"].default_value = 0.2
        bsdf.inputs["Alpha"].default_value = 0.35  # Transparenz-Grad (0 = unsichtbar, 1 = opak)
    return mat


def find_image_path(filename):
    """Sucht eine Bilddatei an mehreren plausiblen Orten, weil je nach
    Aufruf-Art (gespeicherte .py-Datei, Blender-Text-Editor, headless) unterschiedliche
    Ordner als "Skript-Ordner" gelten. Wird sowohl für das Zifferblatt als auch
    für alle Tierkreiszeichen-Bilder verwendet."""
    candidates = []
    if "__file__" in globals():
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    if bpy.data.filepath:
        candidates.append(os.path.dirname(bpy.data.filepath))  # Ordner der .blend-Datei
    candidates.append(os.getcwd())

    for folder in candidates:
        path = os.path.join(folder, filename)
        if os.path.isfile(path):
            return path, candidates
    return None, candidates


def find_dial_image_path():
    return find_image_path(DIAL_IMAGE_FILENAME)


_figure_material_cache = {}  # Dateiname -> (Material, Image-Breite/Höhe oder None)


def get_or_create_figure_material(image_filename):
    """Lädt ein Tierkreiszeichen-Bild (mit Transparenz) als Material - eine
    Kachel pro Bilddatei, gecacht. Gibt (material, aspect_ratio) zurück, wobei
    aspect_ratio = Bildbreite/Bildhöhe ist (für die passende Seitenverhältnis-
    Berechnung der Bild-Ebene); aspect_ratio=1.0 als Fallback, falls das Bild
    nicht gefunden wird (dann einfarbiges Gold-Ersatzmaterial)."""
    if image_filename in _figure_material_cache:
        return _figure_material_cache[image_filename]

    material_name = f"Tierkreiszeichen_{os.path.splitext(image_filename)[0]}"
    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    # WICHTIG: 'CLIP' statt 'BLEND' - BLEND-Transparenz wird in Eevee pro Objekt
    # sortiert (nicht pro Pixel) und kann dadurch, je nach Blickwinkel/Position
    # relativ zu anderen halbtransparenten Flaechen (z.B. der Sternscheibe
    # dahinter), als dunkles/schwarzes Rechteck aufblitzen, bis die Sortierung
    # "aufgeloest" ist (z.B. wenn die Figur weit genug im Vordergrund ist).
    # Da unsere PNGs ohnehin harte Kanten haben (voll deckend oder komplett
    # transparent, keine weichen Verlaeufe), behebt CLIP das Problem sauber:
    # es schreibt pixelgenau in den Tiefenpuffer, keine Sortierprobleme mehr.
    mat.blend_method = 'CLIP'
    mat.alpha_threshold = 0.5
    mat.show_transparent_back = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")

    image_path, searched_folders = find_image_path(image_filename)
    aspect_ratio = 1.0

    if image_path is not None:
        image = bpy.data.images.get(image_filename)
        if image is None:
            image = bpy.data.images.load(image_path)
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.location = (-300, 300)
        tex_node.image = image
        if bsdf is not None:
            links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
            links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])
            bsdf.inputs["Roughness"].default_value = 0.35
            bsdf.inputs["Metallic"].default_value = 0.6  # golden schimmernd, wie im Original
        w, h = image.size
        if h > 0:
            aspect_ratio = w / h
        print(f"[Tierkreiszeichen] '{image_filename}' geladen (Seitenverhältnis {aspect_ratio:.3f}).")
    else:
        print(f"[Tierkreiszeichen] WARNUNG: '{image_filename}' nicht gefunden in {searched_folders} "
              f"- verwende einfarbiges Gold-Ersatzmaterial.")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.83, 0.68, 0.21, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.6
            bsdf.inputs["Roughness"].default_value = 0.35

    _figure_material_cache[image_filename] = (mat, aspect_ratio)
    return mat, aspect_ratio


def get_or_create_dial_material():
    """Zifferblatt-Material: lädt das mitgelieferte Bild als Textur (Base Color).
    Liegt die Datei nicht neben dem Skript, wird ersatzweise ein einfarbiges,
    dunkelblaues Zifferblatt-Material erzeugt (kein Absturz)."""
    if DIAL_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[DIAL_MATERIAL_NAME]

    mat = bpy.data.materials.new(DIAL_MATERIAL_NAME)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")

    image_path, searched_folders = find_dial_image_path()

    if image_path is not None:
        image = bpy.data.images.get(DIAL_IMAGE_FILENAME)
        if image is None:
            image = bpy.data.images.load(image_path)
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.location = (-300, 300)
        tex_node.image = image
        if bsdf is not None:
            links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
            bsdf.inputs["Roughness"].default_value = 0.45
            bsdf.inputs["Metallic"].default_value = 0.0
        print(f"[Zifferblatt] Bild gefunden und geladen: {image_path}")
    else:
        msg = (f"'{DIAL_IMAGE_FILENAME}' wurde in keinem dieser Ordner gefunden: "
               f"{searched_folders} - verwende einfarbiges Ersatz-Zifferblatt. Bitte die "
               f"Bilddatei in einen dieser Ordner legen (am einfachsten: selben Ordner wie "
               f"die gespeicherte .blend-Datei) und das Skript erneut ausführen.")
        print(f"[Zifferblatt] WARNUNG: {msg}")

        # Zusätzlich als gut sichtbares Popup in Blender selbst (nicht nur Konsole):
        def _draw_warning(self, context):
            self.layout.label(text=f"Zifferblatt-Bild nicht gefunden: {DIAL_IMAGE_FILENAME}")
            self.layout.label(text="Ersatzmaterial (einfarbig) wird verwendet.")

        try:
            bpy.context.window_manager.popup_menu(_draw_warning, title="Zifferblatt-Warnung", icon='ERROR')
        except Exception:
            pass  # Popup ist nur ein Komfort-Extra, kein kritischer Schritt
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.06, 0.09, 0.17, 1.0)  # dunkelblau, wie im Referenzbild
            bsdf.inputs["Roughness"].default_value = 0.5
            bsdf.inputs["Metallic"].default_value = 0.0
    return mat


def compute_teeth_count(outer_radius):
    return max(MIN_TEETH, round(outer_radius * TEETH_PER_UNIT_RADIUS))


def compute_gear_radii(module, teeth):
    """Liefert die vier für die Evolventenverzahnung nötigen Kreisradien.
    r_pitch (Wälzkreis) bestimmt den korrekten Mittenabstand kämmender Räder;
    r_addendum (Kopfkreis) ist der tatsächliche Außenradius des Rads."""
    r_pitch = module * teeth / 2.0
    r_base = r_pitch * math.cos(PRESSURE_ANGLE)
    r_addendum = r_pitch + ADDENDUM_COEFF * module
    r_dedendum = r_pitch - DEDENDUM_COEFF * module
    return r_pitch, r_base, r_addendum, r_dedendum


def module_for_addendum(target_r_addendum, teeth):
    """Kehrt compute_gear_radii() um: liefert den Modul, der bei gegebener
    Zähnezahl exakt den gewünschten Kopfkreis-Außenradius ergibt
    (r_addendum = module*(teeth/2 + ADDENDUM_COEFF) -> module auflösen).
    Damit lassen sich Zahnräder direkt über ihre gewünschte sichtbare Größe
    definieren, statt den Modul von Hand zu erraten."""
    return target_r_addendum / (teeth / 2.0 + ADDENDUM_COEFF)


def _involute_angle(r_base, r):
    """Evolventenfunktion inv(alpha) = tan(alpha) - alpha für Radius r (>= r_base)
    auf einer Evolvente, die am Grundkreis r_base beginnt."""
    r = max(r, r_base)
    alpha = math.acos(r_base / r)
    return math.tan(alpha) - alpha


def build_involute_profile(module, teeth, segments=INVOLUTE_SEGMENTS):
    """Erzeugt die vollständige, geschlossene Außenkontur eines Zahnrads mit echter
    Evolventenverzahnung als Liste von (x, y)-Punkten (ein Umlauf, alle Zähne)."""
    r_pitch, r_base, r_addendum, r_dedendum = compute_gear_radii(module, teeth)

    # Winkel-Halbbreite eines Zahns am Wälzkreis (Standard, ohne Profilverschiebung):
    # Zahndicke am Wälzkreis = halbe Zahnteilung (pi*modul/2).
    half_tooth_angle = math.pi / (2.0 * teeth)
    inv_at_pitch = _involute_angle(r_base, r_pitch)
    theta_ref = half_tooth_angle + inv_at_pitch

    # Start der Evolvente: normalerweise am Fußkreis; liegt dieser (bei wenigen Zähnen)
    # innerhalb des Grundkreises, beginnt die Evolvente am Grundkreis und ein kurzes
    # radiales Stück bildet den (vereinfachten) Unterschnitt-Übergang zum Fußkreis.
    flank_start_r = max(r_dedendum, r_base)

    # Evolvente von flank_start_r (Fuß- oder Grundkreis) bis zum Kopfkreis,
    # mit aufsteigendem Radius (root -> tip).
    flank_root_to_tip = []
    for i in range(segments + 1):
        t = i / segments
        r = flank_start_r + t * (r_addendum - flank_start_r)
        theta = theta_ref - _involute_angle(r_base, r)
        flank_root_to_tip.append((theta, r))

    needs_root_transition = flank_start_r > r_dedendum + 1e-9
    theta_at_flank_start = flank_root_to_tip[0][0]

    tooth_step = 2.0 * math.pi / teeth
    points = []
    for i in range(teeth):
        offset = i * tooth_step
        # 1) Optionaler Übergang vom Fußkreis zum Grundkreis (linke Seite),
        #    nur bei sehr wenigen Zähnen nötig (Unterschnitt-Fall).
        if needs_root_transition:
            points.append((-theta_at_flank_start + offset, r_dedendum))
        # 2) Linke Flanke: root -> tip
        points.extend((-theta + offset, r) for theta, r in flank_root_to_tip)
        # 3) Rechte Flanke: tip -> root (gespiegelt & umgekehrte Reihenfolge)
        points.extend((theta + offset, r) for theta, r in reversed(flank_root_to_tip))
        # 4) Optionaler Übergang zurück zum Fußkreis (rechte Seite)
        if needs_root_transition:
            points.append((theta_at_flank_start + offset, r_dedendum))
        # Die Zahnlücke zum nächsten Zahn ergibt sich automatisch: der nächste
        # Punkt (nächster Schleifendurchlauf) liegt bei -theta_at_flank_start
        # + offset + tooth_step, wieder auf dem Fußkreis -> flache Lückensohle.

    return [(r * math.cos(theta), r * math.sin(theta)) for theta, r in points], r_addendum


def add_spoked_gear_profile(bm, profile_xy, hub_radius, rim_inner_radius, spoke_width,
                            num_spokes=6, hub_segments=32):
    """Baut das 2D-Profil eines Speichenrads: massiver Zahnkranz (Ring zwischen
    Kopfkreis-Kontur und Innenradius), massive Nabe in der Mitte, und dazwischen
    `num_spokes` gleich dicke, NICHT verjüngende Speichen (parallele Kanten,
    wie im Original-Foto - keine Trapezform). Zwischen den Speichen bleibt die
    Fläche bewusst offen (Fenster), wie bei einem echten Speichenrad."""
    # 1) Zahnkranz: Ring zwischen der Kopfkreis-Kontur (aussen) und einem
    #    Innenkreis (innen) - Innenpunkte liegen jeweils auf demselben Winkel
    #    wie die Aussenkontur, nur mit kleinerem Radius.
    outer_verts = [bm.verts.new((x, y, 0.0)) for x, y in profile_xy]
    inner_verts = []
    for x, y in profile_xy:
        theta = math.atan2(y, x)
        inner_verts.append(bm.verts.new((rim_inner_radius * math.cos(theta),
                                         rim_inner_radius * math.sin(theta), 0.0)))
    n = len(profile_xy)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((outer_verts[i], outer_verts[j], inner_verts[j], inner_verts[i]))

    # 2) Nabe: massive Scheibe in der Mitte (für die Achse).
    hub_verts = [
        bm.verts.new((hub_radius * math.cos(2.0 * math.pi * i / hub_segments),
                      hub_radius * math.sin(2.0 * math.pi * i / hub_segments), 0.0))
        for i in range(hub_segments)
    ]
    bm.faces.new(hub_verts)

    # 3) Speichen: gerade, gleich dicke Baelken (parallele Kanten im Abstand
    #    +/- halbe Speichenbreite von der radialen Mittelachse - dadurch KEINE
    #    Verjuengung nach aussen, anders als eine einfache Trapez-Speiche).
    half_w = spoke_width * 0.5
    for i in range(num_spokes):
        theta = 2.0 * math.pi * i / num_spokes
        dx, dy = math.cos(theta), math.sin(theta)
        px, py = -math.sin(theta), math.cos(theta)
        t_inner = math.sqrt(max(hub_radius ** 2 - half_w ** 2, 0.0))
        t_outer = math.sqrt(max(rim_inner_radius ** 2 - half_w ** 2, 0.0))

        def spoke_point(t, s):
            return (t * dx + s * px, t * dy + s * py, 0.0)

        v_il = bm.verts.new(spoke_point(t_inner, -half_w))
        v_ol = bm.verts.new(spoke_point(t_outer, -half_w))
        v_or = bm.verts.new(spoke_point(t_outer, half_w))
        v_ir = bm.verts.new(spoke_point(t_inner, half_w))
        bm.faces.new((v_il, v_ol, v_or, v_ir))


def build_gear_mesh(name, module, teeth, thickness, outer_radius_dev=None, spoked=False,
                    num_spokes=6, hub_radius_ratio=0.22, rim_inner_ratio=0.915,
                    spoke_width_ratio=0.08):
    """Baut ein Zahnrad mit echter Evolventenverzahnung, oder im Dev-Modus einen
    simplen glatten Zylinder (Performance-Vorschau ohne Zähne). Mit spoked=True
    entsteht ein Speichenrad (6 gleich dicke Speichen, wie im Original-Foto der
    Uhr) statt einer massiven Scheibe - passend für die groesseren Zahnraeder;
    kleinere Zahnraeder bleiben mit spoked=False massiv."""
    bm = bmesh.new()

    if DEV_MODE_NO_TEETH:
        # Dev-Modus: Einfacher Kreis als N-Gon für maximale Performance
        radius = outer_radius_dev if outer_radius_dev is not None else compute_gear_radii(module, teeth)[2]
        segments = 32  # Glattheit des Ersatz-Zylinders
        profile_verts = []
        for i in range(segments):
            angle = i * (2.0 * math.pi / segments)
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            profile_verts.append(bm.verts.new((x, y, 0.0)))

        bm.verts.ensure_lookup_table()
        bm.faces.new(profile_verts)
    else:
        # Normaler Modus: echte Evolventenkontur mit der tatsächlichen Zähnezahl,
        # damit die Zahnteilung exakt zum berechneten Mittenabstand passt.
        profile_xy, _ = build_involute_profile(module, teeth)

        if spoked:
            r_pitch, _r_base, _r_add, _r_ded = compute_gear_radii(module, teeth)
            hub_radius = r_pitch * hub_radius_ratio
            rim_inner_radius = r_pitch * rim_inner_ratio
            spoke_width = r_pitch * spoke_width_ratio
            add_spoked_gear_profile(bm, profile_xy, hub_radius, rim_inner_radius,
                                    spoke_width, num_spokes=num_spokes)
        else:
            profile_verts = [bm.verts.new((x, y, 0.0)) for x, y in profile_xy]
            bm.verts.ensure_lookup_table()
            bm.faces.new(profile_verts)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    # Entlang der lokalen Z-Achse extrudieren, um die Dicke zu erzeugen (alle
    # bisherigen 2D-Flaechen gemeinsam - egal ob 1 massive Flaeche oder viele
    # einzelne Speichenrad-Flaechen).
    all_faces = list(bm.faces)
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=all_faces)
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_axis_mesh(name, radius, length, hollow=False, wall_thickness=0.05):
    bm = bmesh.new()
    segments = 32

    # Äußerer Zylinder
    outer_verts = []
    for i in range(segments):
        angle = i * (2.0 * math.pi / segments)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        outer_verts.append(bm.verts.new((x, y, 0.0)))

    bm.verts.ensure_lookup_table()
    outer_face = bm.faces.new(outer_verts)

    if hollow:
        # Innerer Zylinder für die Hohlachse (Gegenläufige Face-Normalen oder Deckel-Verbindung)
        inner_radius = max(0.01, radius - wall_thickness)
        inner_verts = []
        for i in range(segments - 1, -1, -1):  # Umgekehrte Reihenfolge für korrekte Normale innen
            angle = i * (2.0 * math.pi / segments)
            x = inner_radius * math.cos(angle)
            y = inner_radius * math.sin(angle)
            inner_verts.append(bm.verts.new((x, y, 0.0)))

        bm.verts.ensure_lookup_table()
        # Wir löschen das geschlossene N-Gon und extrudieren stattdessen einen Ring
        bm.faces.remove(outer_face)
        ring_verts = outer_verts[::-1] + inner_verts
        base_face = bm.faces.new(ring_verts)

        extrude_result = bmesh.ops.extrude_face_region(bm, geom=[base_face])
    else:
        extrude_result = bmesh.ops.extrude_face_region(bm, geom=[outer_face])

    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, length))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def get_or_create_axle_steel_material():
    """Zweite Stahl-Variante speziell für einzelne Achsen (z.B. 3_4/8_9) - etwas
    dunkler/kühler als das Zahnrad-Stahl, damit sich Achse und Räder optisch
    leicht unterscheiden, aber erkennbar zur selben Materialfamilie gehören."""
    if AXLE_STEEL_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[AXLE_STEEL_MATERIAL_NAME]

    mat = bpy.data.materials.new(AXLE_STEEL_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.30, 0.32, 0.36, 1.0)  # dunkler, kuehleres Stahlblau-Grau
        bsdf.inputs["Metallic"].default_value = 1.0
        bsdf.inputs["Roughness"].default_value = 0.30  # etwas glaenzender (poliertes Achsenstahl)
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.55
    return mat


def build_axis_object(entry, collection, brass_material, transparent_material, axle_steel_material=None):
    radius = float(entry.get("r", 0.2)) * SCALE
    length = float(entry.get("length", 5.0)) * SCALE
    hollow = bool(entry.get("hollow", False))
    wall_thickness = float(entry.get("wall_thickness", 0.05)) * SCALE

    name = f"Achse_{entry.get('id', 'fix')}"
    mesh = build_axis_mesh(name, radius, length, hollow=hollow, wall_thickness=wall_thickness)

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)

    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )

    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])

    # Material zuweisen: transparent bei Hohlachsen, sonst wahlweise die
    # (dunklere) Achsen-Stahlvariante (entry["steel"]=True) oder Messing/Standard.
    if hollow:
        mat = transparent_material
    elif bool(entry.get("steel", False)) and axle_steel_material is not None:
        mat = axle_steel_material
    else:
        mat = brass_material
    if mesh.materials:
        mesh.materials[0] = mat
    else:
        mesh.materials.append(mat)

    return obj


def get_or_create_star_disc_material():
    """Dunkelblaues Material fuer die Sternscheibe (Hintergrund der Tierkreis-
    figuren), passend zum Zifferblatt-Blauton."""
    if STAR_DISC_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[STAR_DISC_MATERIAL_NAME]
    mat = bpy.data.materials.new(STAR_DISC_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.03, 0.07, 0.22, 1.0)
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.4
    return mat


def build_dial_mesh(name, radius, segments=96):
    """Kreisrunde Scheibe mit einfacher planarer UV-Projektion (Bild füllt den
    Kreis randfüllend aus, passend zum mitgelieferten Zifferblatt-Bild)."""
    bm = bmesh.new()
    verts = []
    for i in range(segments):
        angle = i * (2.0 * math.pi / segments)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        verts.append(bm.verts.new((x, y, 0.0)))

    face = bm.faces.new(verts)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    uv_layer = bm.loops.layers.uv.new()
    for loop in face.loops:
        vx, vy = loop.vert.co.x, loop.vert.co.y
        loop[uv_layer].uv = ((vx / radius + 1.0) / 2.0, (vy / radius + 1.0) / 2.0)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_dial_object(entry, collection, material):
    radius = float(entry.get("radius", 19.0))
    name = f"Zifferblatt_{entry.get('id', '?')}"
    mesh = build_dial_mesh(name, radius)

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )

    if mesh.materials:
        mesh.materials[0] = material
    else:
        mesh.materials.append(material)

    return obj


def add_rod_geometry(bm, radius, y_start, y_end, segments=16):
    """Fügt einen echten zylindrischen Stab entlang der lokalen Y-Achse zu einem
    bestehenden bmesh hinzu (von y_start bis y_end). Wird sowohl vom Sonnen- als
    auch vom Mondzeiger verwendet, damit beide optisch dasselbe dünne Rohr haben."""
    ring_back, ring_front = [], []
    for i in range(segments):
        angle = i * (2.0 * math.pi / segments)
        cx = radius * math.cos(angle)
        cz = radius * math.sin(angle)
        ring_back.append(bm.verts.new((cx, y_start, cz)))
        ring_front.append(bm.verts.new((cx, y_end, cz)))
    bm.verts.ensure_lookup_table()
    for i in range(segments):
        j = (i + 1) % segments
        bm.faces.new((ring_back[i], ring_back[j], ring_front[j], ring_front[i]))
    bm.faces.new(list(reversed(ring_back)))  # Kappe hinten
    bm.faces.new(ring_front)  # Kappe vorne


def add_rod_along_z(bm, radius, z_start, z_end, segments=16, material_index=0,
                    x_offset=0.0, y_offset=0.0):
    """Wie add_rod_geometry, aber entlang der lokalen Z-Achse (vorne/hinten aus
    Kamerasicht) - für die gemeinsame Welle, die je zwei kleine Zahnräder
    verbindet. x_offset/y_offset verschieben die Welle an eine beliebige Stelle
    (z.B. an die Spitze des Zeigerarms)."""
    ring_back, ring_front = [], []
    for i in range(segments):
        angle = i * (2.0 * math.pi / segments)
        cx = radius * math.cos(angle) + x_offset
        cy = radius * math.sin(angle) + y_offset
        ring_back.append(bm.verts.new((cx, cy, z_start)))
        ring_front.append(bm.verts.new((cx, cy, z_end)))
    bm.verts.ensure_lookup_table()
    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append(bm.faces.new((ring_back[i], ring_back[j], ring_front[j], ring_front[i])))
    faces.append(bm.faces.new(list(reversed(ring_back))))
    faces.append(bm.faces.new(ring_front))
    for f in faces:
        f.material_index = material_index


def add_box(bm, x_range, y_range, z_range, material_index=0):
    """Simpler Quader (für Streben und Bodenplatte)."""
    x0, x1 = x_range
    y0, y1 = y_range
    z0, z1 = z_range
    v = {}
    for xi in (x0, x1):
        for yi in (y0, y1):
            for zi in (z0, z1):
                v[(xi, yi, zi)] = bm.verts.new((xi, yi, zi))
    faces = [
        bm.faces.new((v[(x0, y0, z0)], v[(x0, y1, z0)], v[(x0, y1, z1)], v[(x0, y0, z1)])),
        bm.faces.new((v[(x1, y0, z0)], v[(x1, y0, z1)], v[(x1, y1, z1)], v[(x1, y1, z0)])),
        bm.faces.new((v[(x0, y0, z0)], v[(x0, y0, z1)], v[(x1, y0, z1)], v[(x1, y0, z0)])),
        bm.faces.new((v[(x0, y1, z0)], v[(x1, y1, z0)], v[(x1, y1, z1)], v[(x0, y1, z1)])),
        bm.faces.new((v[(x0, y0, z0)], v[(x1, y0, z0)], v[(x1, y1, z0)], v[(x0, y1, z0)])),
        bm.faces.new((v[(x0, y0, z1)], v[(x0, y1, z1)], v[(x1, y1, z1)], v[(x1, y0, z1)])),
    ]
    for f in faces:
        f.material_index = material_index


def add_disc_plate(bm, radius, z_center, thickness, material_index=0, segments=32,
                   x_offset=0.0, y_offset=0.0):
    """Flache, runde Scheibe ('Platine') senkrecht zur Z-Achse - die Wellen der
    Zahnräder laufen durch sie hindurch (rein visuell, keine echten Bohrungen)."""
    verts_bottom = [
        bm.verts.new((radius * math.cos(2 * math.pi * i / segments) + x_offset,
                      radius * math.sin(2 * math.pi * i / segments) + y_offset,
                      z_center - thickness * 0.5))
        for i in range(segments)
    ]
    face_bottom = bm.faces.new(verts_bottom)
    faces_before = set(bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=[face_bottom])
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=[face_bottom])
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    for f in bm.faces:
        if f not in faces_before:
            f.material_index = material_index
    face_bottom.material_index = material_index


def add_hemisphere_shell(bm, radius, thickness, center, segments=32, rings=16,
                         material_index=0, direction=1.0):
    """Hohle Halbkugel-Schale mit echter Wandstärke (Außen- und Innenfläche plus
    Rand) - Portierung der vom Nutzer bereitgestellten, funktionierenden
    create_bowl_hemisphere()-Logik in unser bmesh-System. direction=+1: Kuppel
    öffnet sich nach -Z (Rand bei center.z, Kuppelspitze bei center.z - radius);
    direction=-1: umgekehrt."""
    cx, cy, cz = center
    grid = {}
    for inner in (False, True):
        r = radius - thickness if inner else radius
        for j in range(rings + 1):
            theta = (math.pi / 2.0) * j / rings
            z = cz - direction * r * math.cos(theta)
            ring_r = r * math.sin(theta)
            for i in range(segments):
                phi = 2.0 * math.pi * i / segments
                x = ring_r * math.cos(phi) + cx
                y = ring_r * math.sin(phi) + cy
                grid[(inner, j, i)] = bm.verts.new((x, y, z))

    faces = []
    for inner in (False, True):
        for j in range(rings):
            for i in range(segments):
                i2 = (i + 1) % segments
                a, b = grid[(inner, j, i)], grid[(inner, j, i2)]
                c, d = grid[(inner, j + 1, i2)], grid[(inner, j + 1, i)]
                if inner:
                    faces.append(bm.faces.new((a, d, c, b)))
                else:
                    faces.append(bm.faces.new((a, b, c, d)))
    # Rand (Aequator-Ring) verbindet Aussen- und Innenflaeche
    for i in range(segments):
        i2 = (i + 1) % segments
        a, b = grid[(False, rings, i)], grid[(False, rings, i2)]
        c, d = grid[(True, rings, i2)], grid[(True, rings, i)]
        faces.append(bm.faces.new((a, d, c, b)))

    for f in faces:
        f.material_index = material_index


def build_sun_hand_mesh(name, length, sun_radius, rays, thickness,
                        rod_radius=None, rod_segments=16, ray_length_ratio=1.6,
                        tail_length_ratio=1.3):
    """Zeiger wie auf dem Foto der Lübecker Astronomischen Uhr: ein dünnes,
    rundes goldenes Rohr (echter Zylinder) von der Nabe bis zur Spitze, dort
    eine erhabene goldene KUGEL (kein flaches Medaillon) mit einem Kranz aus
    einzelnen, duennen Strahlenzacken (mit sichtbaren Luecken dazwischen -
    keine geschlossene Zackenscheibe), wie im Original. Das Rohr liegt entlang
    der lokalen Y-Achse ("12-Uhr"-Richtung bei Startwinkel 0); die ganze
    Zeiger-Baugruppe rotiert wie gewohnt um die lokale Z-Achse."""
    if rod_radius is None:
        rod_radius = sun_radius * 0.10  # dünn, wie ein Rohr - nicht wie eine Klinge

    bm = bmesh.new()

    # 1) Rohr: von der Rückseite (Gegengewicht) bis in die Kugel hinein
    #    (Überlappung vermeidet eine Lücke).
    tail_length = sun_radius * tail_length_ratio
    add_rod_geometry(bm, rod_radius, -tail_length, length + sun_radius * 0.3, rod_segments)

    # 1b) Blaue Gegengewichts-Scheibe ganz am Rückende (wie im Original-Vorbild)
    counterweight_radius = rod_radius * 2.2
    counterweight_thickness = rod_radius * 1.1
    add_flat_disc(bm, counterweight_radius, counterweight_thickness,
                  (0.0, -tail_length - counterweight_radius, -counterweight_thickness / 2.0),
                  segments=20, material_index=1)

    # 2) Goldene, gewölbte Kuppe an der Spitze (wie getriebenes Goldblech -
    #    KEINE Vollkugel). Flacher Deckel unten, leichte Wölbung nach oben.
    dome_center = (0.0, length, -sun_radius * 0.15)  # Boden leicht versenkt,
    # damit die Kuppe insgesamt mittig zur Rohr-/Strahlenebene sitzt.
    _add_hemisphere_dome(bm, sun_radius, dome_center, lat_segments=10, lon_segments=24,
                         material_index=0, height_ratio=0.42)

    # 3) Kranz aus einzelnen, duennen Strahlenzacken um die Kugel-Basis, MIT
    #    sichtbaren Luecken dazwischen (nicht als eine durchgehende Zackenscheibe,
    #    sondern als separate, schmale Dreiecke - wie im Original).
    ray_length = sun_radius * ray_length_ratio
    ray_base_half_angle = (2.0 * math.pi / rays) * 0.18  # schmale Basis, deutliche Luecken
    for i in range(rays):
        center_angle = i * (2.0 * math.pi / rays) + math.pi / 2.0
        a0 = center_angle - ray_base_half_angle
        a1 = center_angle + ray_base_half_angle
        base_l = (sun_radius * math.cos(a0), length + sun_radius * math.sin(a0))
        base_r = (sun_radius * math.cos(a1), length + sun_radius * math.sin(a1))
        tip = ((sun_radius + ray_length) * math.cos(center_angle),
               length + (sun_radius + ray_length) * math.sin(center_angle))
        v0 = bm.verts.new((base_l[0], base_l[1], 0.0))
        v1 = bm.verts.new((base_r[0], base_r[1], 0.0))
        v2 = bm.verts.new((tip[0], tip[1], 0.0))
        ray_face = bm.faces.new((v0, v1, v2))
        bmesh.ops.recalc_face_normals(bm, faces=[ray_face])
        extrude_result = bmesh.ops.extrude_face_region(bm, geom=[ray_face])
        extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
        ray_thickness = thickness * 0.4  # Zacken deutlich duenner als die Kugel
        bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, ray_thickness))

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def _add_uv_sphere(bm, radius, center, lat_segments=10, lon_segments=16, material_index_fn=None):
    """Baut eine volle UV-Kugel manuell (Nord-/Südpol als Einzel-Vertex, dazwischen
    Breitenkreise). material_index_fn(face_mittelpunkt) kann pro Fläche einen
    Material-Index zurückgeben (z.B. für die halb gold/halb schwarze Mondkugel)."""
    cx, cy, cz = center
    north = bm.verts.new((cx, cy, cz + radius))
    south = bm.verts.new((cx, cy, cz - radius))
    rings = []
    for i in range(1, lat_segments):
        theta = math.pi * i / lat_segments
        z = radius * math.cos(theta) + cz
        ring_r = radius * math.sin(theta)
        ring = []
        for j in range(lon_segments):
            phi = 2.0 * math.pi * j / lon_segments
            x = ring_r * math.cos(phi) + cx
            y = ring_r * math.sin(phi) + cy
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)

    faces = []
    for j in range(lon_segments):
        j2 = (j + 1) % lon_segments
        faces.append(bm.faces.new((north, rings[0][j2], rings[0][j])))
    for i in range(len(rings) - 1):
        for j in range(lon_segments):
            j2 = (j + 1) % lon_segments
            faces.append(bm.faces.new((rings[i][j], rings[i][j2], rings[i + 1][j2], rings[i + 1][j])))
    for j in range(lon_segments):
        j2 = (j + 1) % lon_segments
        faces.append(bm.faces.new((south, rings[-1][j], rings[-1][j2])))

    if material_index_fn is not None:
        for f in faces:
            f.material_index = material_index_fn(f.calc_center_median())


def _add_hemisphere_dome(bm, radius, center, lat_segments=8, lon_segments=16,
                         material_index=0, height_ratio=1.0):
    """Baut eine massive, nach oben gewölbte Kuppel (flacher Deckel am Boden
    bei z=center.z, Kuppelspitze bei z=center.z + radius*height_ratio).
    height_ratio=1.0 ergibt eine volle Halbkugel; kleinere Werte (z.B. 0.35)
    ergeben eine flache Wölbung wie ein getriebenes Goldblech (siehe
    Sonnenzeiger) statt einer Kugelhälfte."""
    cx, cy, cz = center
    pole = bm.verts.new((cx, cy, cz + radius * height_ratio))
    rings = []
    for i in range(1, lat_segments + 1):
        theta = (math.pi / 2.0) * i / lat_segments  # 0 an der Kuppelspitze, pi/2 am Rand (Aequator)
        z = radius * height_ratio * math.cos(theta) + cz
        ring_r = radius * math.sin(theta)
        ring = []
        for j in range(lon_segments):
            phi = 2.0 * math.pi * j / lon_segments
            x = ring_r * math.cos(phi) + cx
            y = ring_r * math.sin(phi) + cy
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)

    faces = []
    for j in range(lon_segments):
        j2 = (j + 1) % lon_segments
        faces.append(bm.faces.new((pole, rings[0][j2], rings[0][j])))
    for i in range(len(rings) - 1):
        for j in range(lon_segments):
            j2 = (j + 1) % lon_segments
            faces.append(bm.faces.new((rings[i][j], rings[i][j2], rings[i + 1][j2], rings[i + 1][j])))
    faces.append(bm.faces.new(list(reversed(rings[-1]))))  # flacher Boden-Deckel

    for f in faces:
        f.material_index = material_index


def add_flat_disc(bm, radius, thickness, center, segments=24, material_index=0):
    """Baut eine einfache flache Scheibe (Gegengewicht) - liegt in der
    XY-Ebene, erstreckt sich nach oben (+Z) um 'thickness'."""
    cx, cy, cz = center
    bottom = [bm.verts.new((cx + radius * math.cos(2 * math.pi * i / segments),
                            cy + radius * math.sin(2 * math.pi * i / segments),
                            cz)) for i in range(segments)]
    face = bm.faces.new(bottom)
    face.material_index = material_index
    bmesh.ops.recalc_face_normals(bm, faces=[face])
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=[face])
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    new_faces = [f for f in extrude_result["geom"] if isinstance(f, bmesh.types.BMFace)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    for f in new_faces:
        f.material_index = material_index


def add_flat_gear(bm, module, teeth, z_center, thickness, material_index=0,
                  x_offset=0.0, y_offset=0.0):
    """Flaches kleines Zahnrad (echte Evolventenverzahnung) in der lokalen
    XY-Ebene, extrudiert entlang Z - wiederverwendet für alle kleinen
    Getrieberäder der Mondphasen-Mechanik."""
    profile_xy, r_addendum = build_involute_profile(module, teeth)
    verts = [bm.verts.new((x + x_offset, y + y_offset, z_center)) for x, y in profile_xy]
    face = bm.faces.new(verts)
    faces_before = set(bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=[face])
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=[face])
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    for f in bm.faces:
        if f not in faces_before:
            f.material_index = material_index
    face.material_index = material_index
    return r_addendum


def _v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _v_normalize(a):
    length = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    return (a[0] / length, a[1] / length, a[2] / length) if length > 1e-9 else a


def build_mitered_pipe_mesh(name, points, radius, segments=24, up_ref=(1.0, 0.0, 0.0)):
    """Portiert 1:1 aus Mondzeiger.py (dort 'create_mitered_pipe'): baut ein
    durchgehendes Rohr aus geraden Zylinder-Segmenten, deren Enden an jedem
    Knick auf Gehrung (Miter) geschnitten sind - wie beim Verbinden echter
    Rohrstücke. Das ist die 'Brücke' (Kröpfung), die über das Mondrad hinweg-
    führt, damit dieses frei drehen kann."""
    pts = [tuple(p) for p in points]
    n_pts = len(pts)
    seg_dirs = [_v_normalize(_v_sub(pts[i + 1], pts[i])) for i in range(n_pts - 1)]

    normals = [seg_dirs[0]]
    for i in range(1, n_pts - 1):
        normals.append(_v_normalize(_v_add(seg_dirs[i - 1], seg_dirs[i])))
    normals.append(seg_dirs[-1])

    n = segments
    verts = []
    ring_offset = []
    for i in range(n_pts):
        p = pts[i]
        axis_dir = seg_dirs[i] if i < n_pts - 1 else seg_dirs[-1]
        u = _v_normalize(_v_sub(up_ref, _v_scale(axis_dir, _v_dot(up_ref, axis_dir))))
        v = _v_cross(axis_dir, u)
        ring_offset.append(len(verts))
        for k in range(n):
            theta = 2 * math.pi * k / n
            radial = _v_add(_v_scale(u, radius * math.cos(theta)),
                            _v_scale(v, radius * math.sin(theta)))
            denom = _v_dot(axis_dir, normals[i])
            t = -_v_dot(radial, normals[i]) / denom if abs(denom) > 1e-6 else 0.0
            verts.append(_v_add(_v_add(p, radial), _v_scale(axis_dir, t)))

    faces = []
    for i in range(n_pts - 1):
        o1, o2 = ring_offset[i], ring_offset[i + 1]
        for k in range(n):
            a, b = o1 + k, o1 + (k + 1) % n
            c, d = o2 + (k + 1) % n, o2 + k
            faces.append((a, b, c, d))

    verts.append(pts[0])
    center_start = len(verts) - 1
    for k in range(n):
        a, b = ring_offset[0] + k, ring_offset[0] + (k + 1) % n
        faces.append((center_start, b, a))
    verts.append(pts[-1])
    center_end = len(verts) - 1
    for k in range(n):
        a, b = ring_offset[-1] + k, ring_offset[-1] + (k + 1) % n
        faces.append((center_end, a, b))

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def add_flat_gear_axis(bm, module, teeth, offset, thickness, axis='Z', material_index=0):
    """Wie 'add_flat_gear', aber achsenfähig: baut das Zahnrad (echte Evolventen-
    verzahnung, dieselbe build_involute_profile()) entlang Z (Standard, wie im
    Original) ODER entlang Y - für unser senkrecht zueinander stehendes
    Zahnradpaar (Mondrad auf der Mondphasenkugel-Welle, Y-Achse; Sonnenrad auf
    der Sonnenzeiger-Welle, Z-Achse), genau wie in Mondzeiger.py."""
    profile_xy, r_addendum = build_involute_profile(module, teeth)

    def pt(u, v, s):
        return (u, s, v) if axis == 'Y' else (u, v, s)

    verts = [bm.verts.new(pt(x, y, offset)) for x, y in profile_xy]
    face = bm.faces.new(verts)
    faces_before = set(bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=[face])
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=[face])
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    vec = (0.0, thickness, 0.0) if axis == 'Y' else (0.0, 0.0, thickness)
    bmesh.ops.translate(bm, verts=extruded_verts, vec=vec)
    for f in bm.faces:
        if f not in faces_before:
            f.material_index = material_index
    face.material_index = material_index
    return r_addendum


def build_moon_gear_mesh(name, module, teeth, thickness, axis='Z'):
    """Eigenständiges Zahnrad-Mesh (ohne Wellenstummel) - Sonnenrad bzw.
    Mondrad des Differenzialgetriebes, mit echter Evolventenverzahnung."""
    bm = bmesh.new()
    r_addendum = add_flat_gear_axis(bm, module, teeth, 0.0, thickness, axis=axis, material_index=0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh, r_addendum


def build_moon_arm_mesh(name, length, rod_radius, tail_length_ratio, ball_radius, segments=16):
    """Nur noch die feste schwarze Halbkugel-Schale an der Spitze (cupt die
    Kugel) - KEIN eigenes Rohr mehr hier (das übernimmt jetzt vollständig
    die Kröpfungs-/Brücken-Röhre, die auf der korrekten, erhöhten Höhe
    ball_center_z bis zur Kugel läuft - sonst gäbe es zwei parallele
    Zeiger-Linien). Material-Index 1 = Schwarzlack (Schale)."""
    bm = bmesh.new()
    br = ball_radius
    tip_y = length  # an dieser Stelle sitzt die Getriebekapsel (Kind-Objekt)

    # Halbkugel-Schale: cupt die Kugel, Rand liegt auf Hoehe der Kugelmitte,
    # Kuppel zeigt nach hinten (-Z). Schwarz lackiert.
    ball_center_z = br * 0.9
    shell_radius = br * 1.05
    shell_thickness = shell_radius * 0.10
    shell_center = (0.0, tip_y, ball_center_z)
    add_hemisphere_shell(bm, shell_radius, shell_thickness, shell_center,
                         segments=28, rings=12, material_index=1, direction=1.0)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_moon_capsule_mesh(name, ball_radius):
    """Die rotierende Baugruppe an der Mondzeiger-Spitze (Kind-Objekt, eigene
    Differenz-Rotation): nur noch die zweifarbige (halb gold poliert / halb
    schwarz lackiert) Mondphasenkugel - keine eigenen Zahnräder mehr an dieser
    Stelle (das Getriebe sitzt jetzt sichtbar an den Radpaaren 3/4 und 8/9 im
    Hauptgetriebe, siehe build_gear_pair_support_object)."""
    bm = bmesh.new()
    br = ball_radius
    ball_center_z = br * 0.9

    # Mondphasenkugel: zweifarbig (Material 0 = Gold poliert, Material 1 =
    # Schwarzlack), Grenze an der Kugel-eigenen Mitte (= aktuelle "Phasengrenze"),
    # sitzt vorne, ragt aus der Schale (siehe Arm-Mesh) heraus.
    ball_center = (0.0, 0.0, ball_center_z)

    def ball_material(face_center):
        return 0 if face_center.z >= ball_center[2] else 1

    _add_uv_sphere(bm, ball_radius, ball_center, lat_segments=24, lon_segments=32,
                   material_index_fn=ball_material)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_gear_pair_support_mesh(name, z_low, z_high, plate_side="high",
                                 gear_thickness=0.25, shaft_radius=0.30,
                                 plate_radius=5.5, plate_thickness=0.35,
                                 strut_size=1.0, margin=0.3):
    """Sichtbare gemeinsame Achse für ein Zahnradpaar auf einer Welle (z.B. Rad
    3+4 oder Rad 8+9), gehalten zwischen einer Platine (transparent) und einer
    kleinen senkrechten Strebe auf einer Bodenplatte - wie im Original-Schema
    beschrieben. Alle Werte hier sind bereits in Welt-Einheiten (die Gear-
    Objekte selbst liegen ja auch unskaliert an ihrer *SCALE-Position), das
    Objekt bekommt daher location.z = 0 und alles ist direkt in der Mesh-
    Geometrie enthalten.
    plate_side="high": Platine an der oberen (z_high, meist dem Zifferblatt
    zugewandten) Seite, Strebe unten. plate_side="low": umgekehrt."""
    bm = bmesh.new()

    shaft_z0 = z_low - margin
    shaft_z1 = z_high + gear_thickness + margin
    add_rod_along_z(bm, shaft_radius, shaft_z0, shaft_z1, segments=20, material_index=0)

    if plate_side == "high":
        plate_z = shaft_z1 + plate_thickness * 0.5 + 0.1
        strut_z = shaft_z0 - strut_size * 0.5 - 0.1
    else:
        plate_z = shaft_z0 - plate_thickness * 0.5 - 0.1
        strut_z = shaft_z1 + strut_size * 0.5 + 0.1

    add_disc_plate(bm, plate_radius, plate_z, plate_thickness, material_index=1, segments=36)

    down_offset = plate_radius * 0.95
    z_min = min(plate_z, strut_z) - 0.3
    z_max = max(plate_z, strut_z) + 0.3
    add_box(bm, x_range=(-down_offset - 0.25, -down_offset),
            y_range=(-plate_radius * 0.35, plate_radius * 0.35),
            z_range=(z_min, z_max), material_index=0)
    add_box(bm, x_range=(-down_offset, 0.0),
            y_range=(-strut_size * 0.5, strut_size * 0.5),
            z_range=(strut_z - strut_size * 0.5, strut_z + strut_size * 0.5),
            material_index=0)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_gear_pair_support_object(entry, collection, brass_material, transparent_material):
    name = f"Radhalterung_{entry.get('id', '?')}"
    z_low = float(entry["z_low"]) * SCALE
    z_high = float(entry["z_high"]) * SCALE
    mesh = build_gear_pair_support_mesh(
        name, z_low, z_high,
        plate_side=entry.get("plate_side", "high"),
        gear_thickness=float(entry.get("gear_thickness", 0.25)) * SCALE,
        shaft_radius=float(entry.get("shaft_radius", 0.30)),
        plate_radius=float(entry.get("plate_radius", 5.5)),
        plate_thickness=float(entry.get("plate_thickness", 0.35)),
        strut_size=float(entry.get("strut_size", 1.0)),
    )
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        0.0,
    )
    mesh.materials.append(brass_material)
    mesh.materials.append(transparent_material)
    add_bevel_modifier(obj)
    return obj


def build_moon_center_gear_mesh(name):
    """Winziges, dekoratives 'Zentralrad auf der Sonnenzeiger-Welle' (siehe
    Getriebe.jpg) - dreht mit dem Sonnenzeiger, sitzt mittig auf der Uhr."""
    bm = bmesh.new()
    gear_profile_xy, r_addendum = build_involute_profile(MOON_GEAR_MODULE, MOON_GEAR_TEETH)
    thickness = r_addendum * 0.6
    verts_bottom = [bm.verts.new((x, y, 0.0)) for x, y in gear_profile_xy]
    face_bottom = bm.faces.new(verts_bottom)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=[face_bottom])
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_star_disc_mesh(name, radius, star_count=90, star_size=0.22, seed=42, segments=96):
    """Sternscheibe: dunkelblaue Kreisscheibe mit kleinen, STARREN goldenen
    Sternen (Material-Index 1), die Teil DESSELBEN Mesh sind wie die Scheibe
    selbst - sie drehen sich also zwangslaeufig MIT der Scheibe (kein
    Gegengewicht, im Gegensatz zu den Tierkreisfiguren, die als separate
    Kind-Objekte gebaut werden, siehe build_zodiac_figure_object)."""
    bm = bmesh.new()

    # Scheibe (dunkelblauer Hintergrund, Material-Index 0)
    disc_verts = [
        bm.verts.new((radius * math.cos(2 * math.pi * i / segments),
                      radius * math.sin(2 * math.pi * i / segments), 0.0))
        for i in range(segments)
    ]
    bm.faces.new(disc_verts)
    for f in bm.faces:
        f.material_index = 0

    faces_before = set(bm.faces)
    rng = random.Random(seed)
    for _ in range(star_count):
        r = radius * 0.94 * math.sqrt(rng.random())  # gleichverteilt über die Fläche
        angle = rng.uniform(0.0, 2.0 * math.pi)
        cx, cy = r * math.cos(angle), r * math.sin(angle)
        # kleiner, vierzackiger Stern (einfaches Rautenkreuz)
        n = 8
        pts = []
        for i in range(n):
            a = 2.0 * math.pi * i / n
            rr = star_size if i % 2 == 0 else star_size * 0.4
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        verts = [bm.verts.new((x, y, 0.0)) for x, y in pts]
        bm.faces.new(verts)

    # Sterne leicht erhaben (Relief) ueber die Scheibenoberflaeche extrudieren
    new_faces = [f for f in bm.faces if f not in faces_before]
    bmesh.ops.recalc_face_normals(bm, faces=new_faces)
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=new_faces)
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, star_size * 0.3))
    for f in bm.faces:
        if f not in faces_before:
            f.material_index = 1  # golden

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_star_disc_object(entry, collection, star_disc_material, brass_material, fps):
    name = f"Sternscheibe_{entry.get('id', '?')}"
    radius = float(entry.get("radius", 17.5))
    image_filename = entry.get("image")

    if image_filename:
        # Echtes Sternhimmel-Bild als Textur - ersetzt die prozeduralen Sterne
        # 1:1 durch die Originalgrafik (dieselbe UV-Mapping-Logik wie beim
        # Zifferblatt, da beides randfuellende Kreisbilder sind).
        mesh = build_dial_mesh(name, radius)
        material, _aspect = get_or_create_figure_material(image_filename)
        materials_to_assign = [material]
    else:
        star_count = int(entry.get("star_count", 90))
        mesh = build_star_disc_mesh(name, radius, star_count=star_count)
        materials_to_assign = [star_disc_material, brass_material]

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )
    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])

    for mat in materials_to_assign:
        mesh.materials.append(mat)

    direction = float(entry.get("dir", STAR_DISC_DIR))
    speed = float(entry.get("speed", STAR_DISC_SPEED))
    animate_spin(obj, axis_letter, direction, speed, fps)
    return obj, direction, speed


def build_zodiac_figure_mesh(name, height, aspect_ratio, vertical_anchor="bottom"):
    """Flache Bild-Ebene für ein Tierkreiszeichen (echtes PNG mit Transparenz,
    kein Platzhalter-Modell nötig). Liegt in der lokalen XY-Ebene, "oben"
    (Bildkopf) entlang lokal +Y, UV-Koordinaten decken das Bild exakt ab.
    Seitenverhältnis (aspect_ratio = Bildbreite/-höhe) sorgt dafür, dass das
    Bild nicht verzerrt wird. vertical_anchor="bottom": Ankerpunkt (0,0) liegt
    an der Unterkante (wie bei stehenden Figuren, "Fuesse" am Orbit-Punkt);
    "center": Ankerpunkt liegt in der Bildmitte (fuer das zentrale, kreisrunde
    Heiland-Medaillon)."""
    half_h = height * 0.5
    half_w = height * aspect_ratio * 0.5
    y_bottom = -half_h if vertical_anchor == "center" else 0.0
    y_top = half_h if vertical_anchor == "center" else height

    bm = bmesh.new()
    v_bl = bm.verts.new((-half_w, y_bottom, 0.0))
    v_br = bm.verts.new((half_w, y_bottom, 0.0))
    v_tr = bm.verts.new((half_w, y_top, 0.0))
    v_tl = bm.verts.new((-half_w, y_top, 0.0))
    face = bm.faces.new((v_bl, v_br, v_tr, v_tl))
    bmesh.ops.recalc_face_normals(bm, faces=[face])

    uv_layer = bm.loops.layers.uv.new()
    uv_coords = {v_bl: (0.0, 0.0), v_br: (1.0, 0.0), v_tr: (1.0, 1.0), v_tl: (0.0, 1.0)}
    for loop in face.loops:
        loop[uv_layer].uv = uv_coords[loop.vert]

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_zodiac_figure_object(entry, collection, fps, parent_obj, parent_dir, parent_speed):
    """Baut eine Tierkreisfigur (aus dem mitgelieferten PNG-Bild) als KIND-
    Objekt der Sternscheibe und sorgt für die "schwerkraftgefuehrte" aufrechte
    Haltung:

    PHYSIKALISCHER HINTERGRUND: Am Original haengt hinter jeder Figur ein
    Gegengewicht. Dreht sich die Sternscheibe, sorgt die Schwerkraft dafuer,
    dass das Gewicht immer nach unten haengt - die Figur behaelt dadurch ihre
    absolute (Welt-)Ausrichtung bei, waehrend sie mit der Scheibe auf einer
    Kreisbahn "mitfaehrt". Das ist exakt das Prinzip einer Riesenrad-Gondel:
    Die Gondel umkreist die Radnabe, dreht sich dabei aber NICHT um die
    eigene Achse.

    UMSETZUNG (ohne Physik-Simulation, rein kinematisch): Die Figur wird als
    Kind-Objekt der Scheibe positioniert (ihre ORBITALE Position - der Umlauf
    um das Scheibenzentrum - ergibt sich dadurch automatisch aus der Scheiben-
    rotation). Zusaetzlich bekommt sie ihre EIGENE Rotationsanimation um die
    lokale Z-Achse mit exakt ENTGEGENGESETZTER Drehrichtung/-geschwindigkeit
    der Scheibe. Da beide Rotationen um dieselbe Achse (Z) erfolgen, addieren
    sie sich einfach: Welt-Rotation der Figur = Scheiben-Rotation + Figur-
    Eigenrotation = Scheiben-Rotation + (-Scheiben-Rotation) = 0 - die Figur
    steht also zu JEDEM Zeitpunkt exakt so aufrecht wie beim Start, ohne dass
    einzelne Keyframes pro Figur von Hand berechnet werden muessen (effizient:
    nur 2 Keyframes + F-Curve-Extrapolation, wie ueberall sonst im Skript).

    UNTERSCHIEDLICHE LOKALE ACHSEN: Falls ein Bild nicht mit "oben" = +Y
    ausgerichtet ist, kann `model_rotation_correction_deg` einen einmaligen,
    STATISCHEN Korrekturwinkel (in Grad, um die lokale Z-Achse) vorgeben -
    dieser wird direkt ins Mesh gebacken (nicht mit-animiert), sodass die
    Gegenrotation unabhaengig davon exakt aufgeht.
    """
    orbit_radius = float(entry.get("orbit_radius", 12.0))
    angle_deg = float(entry.get("angle_deg", 0.0))
    angle = math.radians(angle_deg)
    correction_deg = float(entry.get("model_rotation_correction_deg", 0.0))
    height = float(entry.get("height", 3.94))
    # Freier Feinversatz (in denselben Welt-Einheiten wie orbit_radius) - wird
    # NACH der Kreisformel addiert, damit man eine Figur bei Bedarf einfach
    # "nachschieben" kann, ohne angle_deg/orbit_radius neu ausrechnen zu muessen.
    x_offset = float(entry.get("x_offset", 0.0))
    y_offset = float(entry.get("y_offset", 0.0))
    image_filename = entry["image"]

    material, aspect_ratio = get_or_create_figure_material(image_filename)

    name = f"Tierkreiszeichen_{entry.get('id', '?')}"
    vertical_anchor = entry.get("vertical_anchor", "center")
    mesh = build_zodiac_figure_mesh(name, height, aspect_ratio, vertical_anchor=vertical_anchor)

    # Statische Achsenkorrektur direkt in die Mesh-Geometrie backen (siehe
    # Docstring) - dreht NUR die Vertices, keine Objekt-Rotation, damit die
    # spaetere Gegenrotations-Animation unangetastet bleibt.
    if abs(correction_deg) > 1e-9:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.rotate(bm, verts=bm.verts,
                         cent=(0.0, 0.0, 0.0),
                         matrix=mathutils.Matrix.Rotation(math.radians(correction_deg), 3, 'Z'))
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)

    # Position IM LOKALEN Koordinatensystem der Sternscheibe (nicht *SCALE,
    # da die Scheibe selbst schon in "finalen" Welt-Einheiten gebaut ist -
    # dieselbe Konvention wie bei der Mondzeiger-Kapsel).
    obj.location = (orbit_radius * math.cos(angle) + x_offset,
                    orbit_radius * math.sin(angle) + y_offset, 0.05)
    obj.rotation_euler = (0.0, 0.0, 0.0)

    mesh.materials.append(material)

    obj.parent = parent_obj  # erbt Umlaufbewegung der Scheibe automatisch

    # Exakte Gegenrotation: gleiche Geschwindigkeit, entgegengesetzte Richtung.
    animate_spin(obj, "z", -parent_dir, parent_speed, fps)
    return obj


def build_hand_object(entry, collection, material, fps):
    length = float(entry.get("length", 17.0))
    sun_radius = float(entry.get("sun_radius", 3.2))
    rays = int(entry.get("rays", 12))
    thickness = float(entry.get("thickness", 0.35))

    name = f"Zeiger_{entry.get('id', '?')}"
    mesh = build_sun_hand_mesh(name, length, sun_radius, rays, thickness)

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )

    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])

    if mesh.materials:
        mesh.materials[0] = material
    else:
        mesh.materials.append(material)
    mesh.materials.append(get_or_create_counterweight_material())

    add_bevel_modifier(obj)

    # Bewusst identisch zu Rad 6 (+5): dieselbe Achse, dieselbe Drehrichtung/-geschwindigkeit.
    direction = float(entry.get("dir", SHAFT_56_DIR))
    speed = float(entry.get("speed", SHAFT_56_SPEED))
    animate_spin(obj, axis_letter, direction, speed, fps)

    return obj


def build_moon_hand_object(entry, collection, brass_material, moon_material, transparent_material, fps):
    """Portiert die vollständige Getriebe-Geometrie aus Mondzeiger.py (nicht nur
    das Grundprinzip!) - insbesondere:
      - die Brücke ('Kröpfung') aus Gehrungsrohr-Segmenten, die über das
        Mondrad hinwegführt, damit dieses frei drehen kann,
      - das senkrecht zueinander stehende Zahnradpaar (Mondrad auf der
        Mondphasenkugel-Welle = Y-Achse, Sonnenrad auf der Sonnenzeiger-Welle
        = Z-Achse) mit exakt berechnetem, tangentialem Berührpunkt,
      - Kugel UND Mondrad als gemeinsam rotierende Einheit (beide Kinder
        desselben 'Drehachse'-Empties, wie in Mondzeiger.py - nicht die Kugel
        als Kind des Rads, sondern beide auf derselben Welle sitzend).
    Einziger Unterschied zu Mondzeiger.py: die Zähne selbst sind jetzt echte
    Evolventenzähne (add_flat_gear_axis/build_involute_profile) statt der
    einfachen Sägezahn-Silhouette, wie gewünscht "mit der Technik aus
    AstroUhr etwas besser modelliert"."""
    length = float(entry.get("length", 14.5))
    ball_radius = float(entry.get("ball_radius", 1.1))
    rod_radius_ratio = float(entry.get("rod_radius_ratio", 0.16))
    tail_length_ratio = float(entry.get("tail_length_ratio", 0.6))
    rod_radius = ball_radius * rod_radius_ratio

    axis_letter = str(entry.get("axis", "z")).lower()
    arm_dir = float(entry.get("dir", SHAFT_10_DIR))
    arm_speed = float(entry.get("speed", SHAFT_10_SPEED))
    sun_dir = float(entry.get("sun_dir", SHAFT_56_DIR))
    sun_speed = float(entry.get("sun_speed", SHAFT_56_SPEED))

    base_location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )
    axis_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])

    # --- 1) Der Arm (Elternobjekt): Rohr + feste Schale - UNVERAENDERT wie
    #     zuvor, liefert bereits das lange, gerade Rohr bis zur Kugel. ---
    arm_name = f"Zeiger_{entry.get('id', '?')}"
    arm_mesh = build_moon_arm_mesh(arm_name, length, rod_radius, tail_length_ratio, ball_radius)
    arm_obj = bpy.data.objects.new(arm_name, arm_mesh)
    collection.objects.link(arm_obj)
    arm_obj.location = base_location
    arm_obj.rotation_euler = axis_euler
    arm_mesh.materials.append(brass_material)
    arm_mesh.materials.append(moon_material)
    add_bevel_modifier(arm_obj)
    animate_spin(arm_obj, axis_letter, arm_dir, arm_speed, fps)

    # --- 2) Getriebe-Geometrie (wie in Mondzeiger.py hergeleitet und dort
    #     numerisch verifiziert). R = Zielradius der beiden Räder (Versuchs-
    #     wert: halber Mondkugelradius). ACHSE_LAENGE = Abstand Kugel<->
    #     gemeinsamer Drehachse MINUS R (nicht "length" selbst!) - siehe
    #     Herleitung: die gemeinsame Drehachse beider Wellen (Mondzeiger-
    #     Welle/Sonnenzeiger-Welle, hier "base_location") liegt nicht direkt
    #     am Zahnrad, sondern um R davon versetzt, damit das (mit dem Arm
    #     umlaufende) Mondrad ständig im selben Abstand zum ortsfesten
    #     Sonnenrad bleibt (klassisches Planetengetriebe). ---
    n_teeth_sun = int(entry.get("teeth_sun", MOON_GEAR_TEETH))
    n_teeth_moon = int(entry.get("teeth_moon", MOON_GEAR_TEETH))
    radius_ratio = float(entry.get("gear_radius_ratio", MOON_GEAR_RADIUS_RATIO))
    R = ball_radius * radius_ratio
    module_sun = module_for_addendum(R, n_teeth_sun)
    module_moon = module_for_addendum(R, n_teeth_moon)
    GEAR_DICKE = R * 0.35
    ACHSE_LAENGE = length - R

    # --- 2a) Mondrad ('n-zähniges Rad auf der Mondphasenkugel-Welle') samt
    #     Bruecke ('Kroepfung') - Kinder eines gemeinsamen 'Drehachse'-Empty,
    #     das an der Kugel-Position (Arm-Spitze) sitzt und sich mit der
    #     korrekten Differenzdrehzahl dreht.
    #
    #     WICHTIG (Bugfix): build_moon_capsule_mesh baut die Kugel NICHT bei
    #     (0,0,0), sondern bei (0,0,ball_center_z) - ball_center_z = 0.9*
    #     ball_radius. Die Drehachse muss daher GENAU DORT liegen (nicht bei
    #     z=0), sonst rotiert die Kugel nicht um ihren eigenen Mittelpunkt,
    #     sondern schwenkt exzentrisch im Kreis um die falsche Achse -
    #     dadurch "verliert die Schale die Kugel". ---
    ball_center_z = ball_radius * 0.9
    drehachse_name = f"Drehachse_{entry.get('id', '?')}"
    drehachse_obj = bpy.data.objects.new(drehachse_name, None)
    collection.objects.link(drehachse_obj)
    drehachse_obj.parent = arm_obj
    drehachse_obj.location = (0.0, length, ball_center_z)

    moon_gear_name = f"Mondrad_{entry.get('id', '?')}"
    moon_gear_mesh, _ = build_moon_gear_mesh(moon_gear_name, module_moon, n_teeth_moon, GEAR_DICKE, axis='Y')
    moon_gear_obj = bpy.data.objects.new(moon_gear_name, moon_gear_mesh)
    collection.objects.link(moon_gear_obj)
    moon_gear_obj.parent = drehachse_obj
    moon_gear_obj.location = (0.0, -ACHSE_LAENGE - GEAR_DICKE, 0.0)
    moon_gear_mesh.materials.append(brass_material)
    add_bevel_modifier(moon_gear_obj)

    kapsel_name = f"Getriebekapsel_{entry.get('id', '?')}"
    kapsel_mesh = build_moon_capsule_mesh(kapsel_name, ball_radius)
    kapsel_obj = bpy.data.objects.new(kapsel_name, kapsel_mesh)
    collection.objects.link(kapsel_obj)
    kapsel_obj.parent = drehachse_obj
    # Kompensiert den in der Kugel-Mesh bereits eingebackenen Versatz
    # (ball_center_z), damit die Kugel exakt im Ursprung der Drehachse
    # sitzt - dort, wo jetzt auch die Drehachse selbst liegt (s.o.).
    kapsel_obj.location = (0.0, 0.0, -ball_center_z)
    kapsel_mesh.materials.append(brass_material)
    kapsel_mesh.materials.append(moon_material)
    add_bevel_modifier(kapsel_obj)

    # Brücke (Kröpfung): führt vom Rohr aus über das Mondrad hinweg - kurzer
    # Stummel "hinter der Uhr" -> hoch -> rüber (über dem Zahnrad) -> runter
    # auf Rohrhöhe. Kind des ARMS (nicht der Drehachse!), da sie sich NICHT
    # mit dem Mondrad mitdrehen darf. Alle Z-Koordinaten liegen jetzt auf
    # Höhe von ball_center_z (statt 0), da die ganze Mechanik der Drehachse
    # gefolgt ist (s. Bugfix oben) - schmalerer Rohrradius (dünnere Achse).
    # STUMMEL_LAENGE verlängert (nach hinten hin), damit das Gegengewicht
    # weiter hinten sitzt, wie im Original-Vorbild.
    BRUECKE_HOEHE = ball_center_z + R * 1.33
    BRUECKE_RAND = R * 0.25
    STUMMEL_LAENGE = R * 3.2
    GEAR_Y_NAH = R
    GEAR_Y_FERN = R - GEAR_DICKE
    bruecke_pfad = [
        (0.0, GEAR_Y_FERN - BRUECKE_RAND - STUMMEL_LAENGE, ball_center_z),
        (0.0, GEAR_Y_FERN - BRUECKE_RAND, ball_center_z),
        (0.0, GEAR_Y_FERN - BRUECKE_RAND, BRUECKE_HOEHE),
        (0.0, GEAR_Y_NAH + BRUECKE_RAND, BRUECKE_HOEHE),
        (0.0, GEAR_Y_NAH + BRUECKE_RAND, ball_center_z),
        (0.0, length, ball_center_z),  # durchgehend bis zur Kugel auf erhöhter Höhe
    ]
    bruecke_name = f"Kroepfung_{entry.get('id', '?')}"
    # Dünnere Achse (Rohrradius nah am bestehenden Rohr statt deutlich dicker)
    bruecke_mesh = build_mitered_pipe_mesh(bruecke_name, bruecke_pfad, radius=rod_radius * 0.9)
    bruecke_obj = bpy.data.objects.new(bruecke_name, bruecke_mesh)
    collection.objects.link(bruecke_obj)
    bruecke_obj.parent = arm_obj
    # Transparentes Gold, damit die (dunkle) Mondkugel-Welle darin sichtbar bleibt
    bruecke_mesh.materials.append(get_or_create_transparent_gold_material())
    add_bevel_modifier(bruecke_obj)

    # Dünne, dunkle Innenwelle - die "Mondkugel-Welle" selbst - läuft entlang
    # desselben Pfads, aber dünner, damit sie durch das transparente Gold-
    # Rohr der Brücke hindurch sichtbar ist.
    welle_name = f"Mondkugel_Welle_{entry.get('id', '?')}"
    welle_mesh = build_mitered_pipe_mesh(welle_name, bruecke_pfad, radius=rod_radius * 0.35)
    welle_obj = bpy.data.objects.new(welle_name, welle_mesh)
    collection.objects.link(welle_obj)
    welle_obj.parent = arm_obj
    welle_mesh.materials.append(moon_material)
    add_bevel_modifier(welle_obj)

    # Blaue Gegengewichts-Scheibe am Stummel-Ende (Rückseite, "hinter der
    # Uhr") - analog zum Sonnenzeiger, dessen langem Arm ebenfalls ein
    # solches Gegengewicht am kurzen Ende gegenübersteht.
    gegengewicht_name = f"Gegengewicht_{entry.get('id', '?')}"
    gg_radius = rod_radius * 2.2
    gg_thickness = rod_radius * 1.1
    bm_gg = bmesh.new()
    add_flat_disc(bm_gg, gg_radius, gg_thickness,
                  (bruecke_pfad[0][0], bruecke_pfad[0][1] - gg_radius, bruecke_pfad[0][2] - gg_thickness / 2.0),
                  segments=20, material_index=0)
    bmesh.ops.recalc_face_normals(bm_gg, faces=bm_gg.faces)
    gg_mesh = bpy.data.meshes.new(gegengewicht_name + "_Mesh")
    bm_gg.to_mesh(gg_mesh)
    bm_gg.free()
    gg_mesh.update()
    gg_obj = bpy.data.objects.new(gegengewicht_name, gg_mesh)
    collection.objects.link(gg_obj)
    gg_obj.parent = arm_obj
    gg_mesh.materials.append(get_or_create_counterweight_material())
    add_bevel_modifier(gg_obj)

    # --- 2b) Sonnenrad ('n-zähniges Rad auf der Sonnenzeiger-Welle') - eigene,
    #     unabhaengige Achse ('Sonnenachse'), an DERSELBEN Stelle wie der Arm
    #     selbst (konzentrische Wellen), NICHT Kind des Arms. Ebenfalls auf
    #     Höhe ball_center_z angehoben (Bugfix, s.o.) - vorher lag es zu
    #     tief (unterhalb des Zifferblatts versteckt, daher "fehlte" es). ---
    sonnenachse_name = f"Sonnenachse_{entry.get('id', '?')}"
    sonnenachse_obj = bpy.data.objects.new(sonnenachse_name, None)
    collection.objects.link(sonnenachse_obj)
    sonnenachse_obj.location = base_location
    sonnenachse_obj.rotation_euler = axis_euler
    animate_spin(sonnenachse_obj, "z", sun_dir, sun_speed, fps)

    sun_gear_name = f"Sonnenrad_{entry.get('id', '?')}"
    sun_gear_mesh, _ = build_moon_gear_mesh(sun_gear_name, module_sun, n_teeth_sun, GEAR_DICKE, axis='Z')
    sun_gear_obj = bpy.data.objects.new(sun_gear_name, sun_gear_mesh)
    collection.objects.link(sun_gear_obj)
    sun_gear_obj.parent = sonnenachse_obj
    sun_gear_obj.location = (0.0, 0.0, ball_center_z - R - GEAR_DICKE)
    sun_gear_mesh.materials.append(brass_material)
    add_bevel_modifier(sun_gear_obj)

    # Kontrolle Berührpunkt (siehe Herleitung, numerisch verifiziert): beide
    # Zahnkränze berühren sich exakt dort, wo der Abstand ihrer Kreiszentren
    # gleich R ist - das gilt unabhängig von der Höhenverschiebung um
    # ball_center_z (reine Parallelverschiebung, ändert nichts an der
    # relativen Geometrie): Mondrad-Zahnkranz liegt (Arm-lokal) auf dem Kreis
    # um (0,R,ball_center_z), Radius R, in der XZ-Ebene -> unterster Punkt
    # (0,R,ball_center_z-R). Sonnenrad-Zahnkranz liegt auf dem Kreis um
    # (0,0,ball_center_z-R), Radius R, in der XY-Ebene -> derselbe Punkt
    # liegt exakt darauf (Abstand von (0,0) zu (0,R) = R).

    # --- 3) Kinematik: allgemeine Planetengetriebe-Formel (Wechsel ins
    #     mitrotierende Bezugssystem des Arms/Trägers):
    #       omega_P = omega_C*(1 + N_S/N_P) - (N_S/N_P)*omega_S
    #     Dem 'Drehachse'-Empty (trägt Kugel UND Mondrad gemeinsam) wird nur
    #     die ZUSAETZLICHE (relative) Drehzahl omega_P - omega_C gegeben, da
    #     es als Kind des Arms dessen omega_C bereits automatisch erbt. Bei
    #     gleicher Zähnezahl (N_S=N_P): omega_P = 2*omega_C - omega_S
    #     ("Münzen-Paradoxon"). ---
    omega_C = arm_dir * arm_speed
    omega_S = sun_dir * sun_speed
    ratio = n_teeth_sun / n_teeth_moon
    omega_P = omega_C * (1.0 + ratio) - ratio * omega_S
    rel = omega_P - omega_C
    animate_local_spin(drehachse_obj, 1, 1.0 if rel >= 0 else -1.0, abs(rel), fps)

    return arm_obj


def build_moon_center_gear_object(entry, collection, brass_material, fps):
    name = f"Zentralrad_{entry.get('id', '?')}"
    mesh = build_moon_center_gear_mesh(name)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )
    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])
    if mesh.materials:
        mesh.materials[0] = brass_material
    else:
        mesh.materials.append(brass_material)
    add_bevel_modifier(obj)

    direction = float(entry.get("dir", SHAFT_56_DIR))
    speed = float(entry.get("speed", SHAFT_56_SPEED))
    animate_spin(obj, axis_letter, direction, speed, fps)
    return obj


def add_bevel_modifier(obj):
    bevel = obj.modifiers.new(name="Kantenverrundung", type='BEVEL')
    bevel.width = BEVEL_WIDTH
    bevel.segments = 3
    bevel.limit_method = 'ANGLE'
    bevel.angle_limit = math.radians(35.0)


def animate_spin(obj, axis_letter, direction, speed, fps):
    """Setzt eine linear extrapolierte Dreh-Animation um die lokale Z-Achse."""
    total_seconds = CYCLE_FRAMES / fps
    target_angle = direction * speed * BASE_ANGULAR_SPEED * total_seconds

    obj.rotation_mode = 'XYZ'
    z_index = 2  # lokale Z-Achse

    obj.rotation_euler[z_index] = 0.0
    obj.keyframe_insert(data_path="rotation_euler", index=z_index, frame=1)
    obj.rotation_euler[z_index] = target_angle
    obj.keyframe_insert(data_path="rotation_euler", index=z_index, frame=1 + CYCLE_FRAMES)

    # Korrigierter Zugriff für Blender 4.x+
    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        curves = getattr(action, "fcurves", None)
        if curves is None:
            curves = getattr(action, "curves", [])

        fcurve = next(
            (fc for fc in curves if fc.data_path == "rotation_euler" and fc.array_index == z_index),
            None,
        )
        if fcurve is not None:
            fcurve.extrapolation = 'LINEAR'
            for keyframe in fcurve.keyframe_points:
                keyframe.interpolation = 'LINEAR'


def animate_local_spin(obj, axis_index, direction, speed, fps):
    """Wie animate_spin(), aber OHNE die AXIS_ALIGN_EULER-Vorausrichtung -
    animiert direkt den angegebenen lokalen Euler-Index (0=X, 1=Y, 2=Z).
    Nötig für 'Drehachse' (Mondkugel-Eigendrehung um die lokale Y-Achse):
    deren Kinder (Mondrad, Kapsel) sind relativ zu einer UNROTIERTEN
    lokalen Basis positioniert - eine zusätzliche statische Vor-Rotation
    (wie sie animate_spin voraussetzt) würde diese Positionen mitverdrehen
    und die sorgfältig berechnete Getriebegeometrie verschieben."""
    total_seconds = CYCLE_FRAMES / fps
    target_angle = direction * speed * BASE_ANGULAR_SPEED * total_seconds

    obj.rotation_mode = 'XYZ'
    obj.rotation_euler[axis_index] = 0.0
    obj.keyframe_insert(data_path="rotation_euler", index=axis_index, frame=1)
    obj.rotation_euler[axis_index] = target_angle
    obj.keyframe_insert(data_path="rotation_euler", index=axis_index, frame=1 + CYCLE_FRAMES)

    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        curves = getattr(action, "fcurves", None)
        if curves is None:
            curves = getattr(action, "curves", [])
        fcurve = next(
            (fc for fc in curves if fc.data_path == "rotation_euler" and fc.array_index == axis_index),
            None,
        )
        if fcurve is not None:
            fcurve.extrapolation = 'LINEAR'
            for keyframe in fcurve.keyframe_points:
                keyframe.interpolation = 'LINEAR'


def build_gear_object(entry, collection, material, fps):
    # Zuerst prüfen, ob Zähnezahl da ist, sonst Fallback über einen groben Radius-Wunsch
    if "teeth" in entry:
        teeth = int(entry["teeth"])
    else:
        outer_r_input = float(entry.get("r", 2.0))
        teeth = compute_teeth_count(outer_r_input * SCALE)

    # --- ECHTE EVOLVENTEN-RADIEN ÜBER DAS MODUL ---
    # r_pitch (Wälzkreis) ist die Grundlage für den korrekten Mittenabstand kämmender
    # Räder (Positionen in GEAR_DATA sind entsprechend darauf abgestimmt).
    # r_addendum (Kopfkreis) ist der tatsächliche, sichtbare Außenradius.
    r_pitch, r_base, r_addendum, r_dedendum = compute_gear_radii(GEAR_MODULE, teeth)
    outer_radius = r_addendum
    # -----------------------------------------------

    # Feste Dicke oder Standard-Verhältnis
    if "thickness" in entry:
        thickness = float(entry["thickness"]) * SCALE
    else:
        thickness = outer_radius * GEAR_THICKNESS_RATIO

    name = f"Zahnrad_{entry.get('id', '?')}"
    spoked = bool(entry.get("spoked", False))
    mesh = build_gear_mesh(name, GEAR_MODULE, teeth, thickness, outer_radius_dev=outer_radius,
                           spoked=spoked)

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)

    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )

    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])

    if mesh.materials:
        mesh.materials[0] = material
    else:
        mesh.materials.append(material)

    add_bevel_modifier(obj)

    direction = float(entry.get("dir", 1))
    speed = float(entry.get("speed", 1))
    animate_spin(obj, axis_letter, direction, speed, fps)

    return obj


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base if scene.render.fps_base else scene.render.fps
    scene.frame_end = max(scene.frame_end, 1 + CYCLE_FRAMES)

    collection = get_or_create_collection(COLLECTION_NAME)
    clear_collection(collection)

    brass_material = get_or_create_brass_material()
    steel_material = get_or_create_steel_material()
    axle_steel_material = get_or_create_axle_steel_material()
    transparent_material = get_or_create_transparent_material()
    dial_material = get_or_create_dial_material()
    moon_material = get_or_create_moon_material()
    star_disc_material = get_or_create_star_disc_material()
    gear_data = load_gear_data()

    created = []
    named_objects = {}  # id -> Objekt (fuer Parent-Lookups, z.B. Sternscheibe)
    disc_spin_by_id = {}  # id -> (dir, speed) der jeweiligen Scheibe
    for entry in gear_data:
        etype = entry.get("type", "gear")
        if etype == "gear":
            obj = build_gear_object(entry, collection, steel_material, fps)
            created.append(obj)
        elif etype == "axis":
            obj = build_axis_object(entry, collection, brass_material, transparent_material, axle_steel_material)
            created.append(obj)
        elif etype == "dial":
            obj = build_dial_object(entry, collection, dial_material)
            created.append(obj)
        elif etype == "hand":
            obj = build_hand_object(entry, collection, brass_material, fps)
            created.append(obj)
        elif etype == "moon_hand":
            obj = build_moon_hand_object(entry, collection, brass_material, moon_material, transparent_material, fps)
            created.append(obj)
        elif etype == "moon_center_gear":
            obj = build_moon_center_gear_object(entry, collection, brass_material, fps)
            created.append(obj)
        elif etype == "gear_pair_support":
            obj = build_gear_pair_support_object(entry, collection, brass_material, transparent_material)
            created.append(obj)
        elif etype == "star_disc":
            obj, disc_dir, disc_speed = build_star_disc_object(
                entry, collection, star_disc_material, brass_material, fps)
            created.append(obj)
            named_objects[entry.get("id")] = obj
            disc_spin_by_id[entry.get("id")] = (disc_dir, disc_speed)
        elif etype == "zodiac_figure":
            parent_id = entry.get("parent_id")
            parent_obj = named_objects.get(parent_id)
            if parent_obj is None:
                print(f"[Sternscheibe] WARNUNG: parent_id '{parent_id}' fuer Tierkreisfigur "
                      f"'{entry.get('id')}' nicht gefunden (Sternscheibe muss VOR den Figuren "
                      f"in GEAR_DATA stehen) - Figur wird uebersprungen.")
                continue
            parent_dir, parent_speed = disc_spin_by_id[parent_id]
            obj = build_zodiac_figure_object(entry, collection, fps,
                                             parent_obj, parent_dir, parent_speed)
            created.append(obj)

    print(f"[Messingzahnraeder] {len(created)} Objekte erzeugt in Collection '{COLLECTION_NAME}'.")
    for obj, entry in zip(created, [e for e in gear_data if e.get("type") == "gear"]):
        teeth = int(entry["teeth"])
        r_pitch, r_base, r_addendum, r_dedendum = compute_gear_radii(GEAR_MODULE, teeth)
        print(f"  - {obj.name}: {teeth} Zähne -> Wälzkreis {r_pitch:.2f} / Kopfkreis {r_addendum:.2f}, "
              f"speed={entry.get('speed')}, dir={entry.get('dir')}")

    # WICHTIG: Zeitleiste auf Frame 1 setzen. Bei Frame 1 ist die Rotation
    # ALLER animierten Objekte exakt 0 - das entspricht 1:1 den in GEAR_DATA
    # angegebenen angle_deg/orbit_radius-Werten (dem "Design"-Layout). Stand
    # die Zeitleiste beim Ausführen des Skripts auf einem anderen Frame, würde
    # sofort die zu diesem Frame gehörende (bereits gedrehte) Pose angezeigt -
    # das sieht dann so aus, als waeren die Sternbilder "verschoben", obwohl
    # die Werte in GEAR_DATA korrekt sind.
    scene.frame_set(1)


if __name__ == "__main__":
    main()