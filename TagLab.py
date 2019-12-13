# TagLab
# A semi-automatic segmentation tool
#
# Copyright(C) 2019
# Visual Computing Lab
# ISTI - Italian National Research Council
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License (http://www.gnu.org/licenses/gpl.txt)
# for more details.

import sys
import os
import time
import datetime

import json
import numpy as np
import numpy.ma as ma
from skimage import measure

from PyQt5.QtCore import Qt, QSize, QDir, QPoint, QPointF, QLineF, QRectF, QTimer, pyqtSlot, pyqtSignal, QSettings, QFileInfo
from PyQt5.QtGui import QPainterPath, QFont, QColor, QPolygonF, QImage, QPixmap, QIcon, QKeySequence, \
    QPen, QBrush, qRgb, qRed, qGreen, qBlue
from PyQt5.QtWidgets import QApplication, QWidget, QFileDialog, QDialog, QMenuBar, QMenu, QSizePolicy, QScrollArea, QLabel, QToolButton, QPushButton, QSlider, \
    QMessageBox, QGroupBox, QHBoxLayout, QVBoxLayout, QTextEdit, QLineEdit, QGraphicsView, QAction

# PYTORCH
try:
    import torch
    from torch.nn.functional import upsample
except Exception as e:
    print("Incompatible version between pytorch, cuda and python.\n" +
          "Knowing working version combinations are\n: Cuda 10.0, pytorch 1.0.0, python 3.6.8" + str(e))
   # exit()

from collections import OrderedDict

# DEEP EXTREME
import models.deeplab_resnet as resnet
from models.dataloaders import helpers as helpers

# CUSTOM
from source.QtImageViewerPlus import QtImageViewerPlus
from source.QtMapViewer import QtMapViewer
from source.QtMapSettingsWidget import QtMapSettingsWidget
from source.QtInfoWidget import QtInfoWidget
from source.QtProgressBarCustom import QtProgressBarCustom
from source.QtCrackWidget import QtCrackWidget
from source.QtExportWidget import QtExportWidget
#from QtInfoWidget import QtInfoWidget
from source.Blob import Blob
from source.Annotation import Annotation
from source.Labels import Labels, LabelsWidget
from source.MapClassifier import MapClassifier
from source import utils

# LOGGING
import logging

# configure the logger
now = datetime.datetime.now()
LOG_FILENAME = "tool" + now.strftime("%Y-%m-%d-%H-%M") + ".log"
logging.basicConfig(level=logging.DEBUG, filemode='w', filename=LOG_FILENAME, format = '%(asctime)s %(levelname)-8s %(message)s')
logfile = logging.getLogger("tool-logger")


class TagLab(QWidget):

    def __init__(self, parent=None):
        super(TagLab, self).__init__(parent)

        ##### CUSTOM STYLE #####

        self.setStyleSheet("background-color: rgb(55,55,55); color: white")

        ##### DATA INITIALIZATION AND SETUP #####

        # LOAD CONFIGURATION FILE

        f = open("config.json", "r")
        config_dict = json.load(f)
        self.available_classifiers = config_dict["Available Classifiers"]

        logfile.info("Initizialization begins..")

        # MAP VIEWER preferred size (longest side)
        self.MAP_VIEWER_SIZE = 400

        self.working_dir = os.getcwd()
        self.project_name = "NONE"
        self.map_image_filename = "map.png"
        self.map_acquisition_date = "YYYY-MM-DD"
        self.map_px_to_mm_factor = 1.0

        self.project_to_save = ""

        self.recentFileActs = []
        self.maxRecentFiles = 4

        # ANNOTATION DATA
        self.annotations = Annotation()
        self.undo_operations = []
        """Temporary variable to hold the added and removed of the last operation."""
        self.undo_operation =  { "remove":[], "add":[], "class":[] }
        """Max number  of undo operations"""
        self.max_undo = 20

        ##### INTERFACE #####
        #####################

        self.mapWidget = None

        self.tool_used = "MOVE"        # tool currently used
        self.tool_orig = "MOVE"        # tool originally used when a shift key changes the current tool
        self.current_selection = None  # blob currently selected

        ICON_SIZE = 48
        BUTTON_SIZE = 54

        ##### TOP LAYOUT

        ##### LAYOUT EDITING TOOLS (VERTICAL)

        flatbuttonstyle1 = "\
        QPushButton:checked\
        {\
            background-color: rgb(100,100,100);\
        }\
        QPushButton:hover\
        {\
            border: 1px solid darkgray;\
        }"

        flatbuttonstyle2 = "\
        QPushButton:checked\
        {\
            background-color: rgb(100,100,100);\
        }\
        QPushButton:hover\
        {\
            border: 1px solid rgb(255,100,100);\
        }"

        layout_tools = QVBoxLayout()

        self.btnMove = QPushButton()
        self.btnMove.setEnabled(True)
        self.btnMove.setCheckable(True)
        self.btnMove.setFlat(True)
        self.btnMove.setStyleSheet(flatbuttonstyle1)
        self.btnMove.setMinimumWidth(ICON_SIZE)
        self.btnMove.setMinimumHeight(ICON_SIZE)
        self.btnMove.setIcon(QIcon(os.path.join("icons","move.png")))
        self.btnMove.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.btnMove.setMaximumWidth(BUTTON_SIZE)
        self.btnMove.setToolTip("Move")
        self.btnMove.clicked.connect(self.move)

        self.btnAssign = QPushButton()
        self.btnAssign.setEnabled(True)
        self.btnAssign.setCheckable(True)
        self.btnAssign.setFlat(True)
        self.btnAssign.setStyleSheet(flatbuttonstyle1)
        self.btnAssign.setMinimumWidth(ICON_SIZE)
        self.btnAssign.setMinimumHeight(ICON_SIZE)
        self.btnAssign.setIcon(QIcon(os.path.join("icons","bucket.png")))
        self.btnAssign.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.btnAssign.setMaximumWidth(BUTTON_SIZE)
        self.btnAssign.setToolTip("Assign class")
        self.btnAssign.clicked.connect(self.assign)

        self.btnEditBorder = QPushButton()
        self.btnEditBorder.setEnabled(True)
        self.btnEditBorder.setCheckable(True)
        self.btnEditBorder.setFlat(True)
        self.btnEditBorder.setStyleSheet(flatbuttonstyle1)
        self.btnEditBorder.setMinimumWidth(ICON_SIZE)
        self.btnEditBorder.setMinimumHeight(ICON_SIZE)
        self.btnEditBorder.setIcon(QIcon(os.path.join("icons","edit.png")))
        self.btnEditBorder.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.btnEditBorder.setMaximumWidth(BUTTON_SIZE)
        self.btnEditBorder.setToolTip("Edit border")
        self.btnEditBorder.clicked.connect(self.editBorder)

        self.btnCut = QPushButton()
        self.btnCut.setEnabled(True)
        self.btnCut.setCheckable(True)
        self.btnCut.setFlat(True)
        self.btnCut.setStyleSheet(flatbuttonstyle1)
        self.btnCut.setMinimumWidth(ICON_SIZE)
        self.btnCut.setMinimumHeight(ICON_SIZE)
        self.btnCut.setIcon(QIcon(os.path.join("icons", "scissors.png")))
        self.btnCut.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.btnCut.setMaximumWidth(BUTTON_SIZE)
        self.btnCut.setToolTip("Cut Segmentation")
        self.btnCut.clicked.connect(self.cut)

        self.btnFreehand = QPushButton()
        self.btnFreehand.setEnabled(True)
        self.btnFreehand.setCheckable(True)
        self.btnFreehand.setFlat(True)
        self.btnFreehand.setStyleSheet(flatbuttonstyle1)
        self.btnFreehand.setMinimumWidth(ICON_SIZE)
        self.btnFreehand.setMinimumHeight(ICON_SIZE)
        self.btnFreehand.setIcon(QIcon(os.path.join("icons","pencil.png")))
        self.btnFreehand.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.btnFreehand.setMaximumWidth(BUTTON_SIZE)
        self.btnFreehand.setToolTip("Freehand segmentation")
        self.btnFreehand.clicked.connect(self.freehandSegmentation)

        self.btnCreateCrack = QPushButton()
        self.btnCreateCrack.setEnabled(True)
        self.btnCreateCrack.setCheckable(True)
        self.btnCreateCrack.setFlat(True)
        self.btnCreateCrack.setStyleSheet(flatbuttonstyle1)
        self.btnCreateCrack.setMinimumWidth(ICON_SIZE)
        self.btnCreateCrack.setMinimumHeight(ICON_SIZE)
        self.btnCreateCrack.setIcon(QIcon(os.path.join("icons","crack.png")))
        self.btnCreateCrack.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.btnCreateCrack.setMaximumWidth(BUTTON_SIZE)
        self.btnCreateCrack.setToolTip("Create crack")
        self.btnCreateCrack.clicked.connect(self.createCrack)

        self.btnRuler = QPushButton()
        self.btnRuler.setEnabled(True)
        self.btnRuler.setCheckable(True)
        self.btnRuler.setFlat(True)
        self.btnRuler.setStyleSheet(flatbuttonstyle1)
        self.btnRuler.setMinimumWidth(ICON_SIZE)
        self.btnRuler.setMinimumHeight(ICON_SIZE)
        self.btnRuler.setIcon(QIcon(os.path.join("icons","ruler.png")))
        self.btnRuler.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.btnRuler.setMaximumWidth(BUTTON_SIZE)
        self.btnRuler.setToolTip("Measure tool")
        self.btnRuler.clicked.connect(self.ruler)



        self.btnDeepExtreme = QPushButton()
        self.btnDeepExtreme.setEnabled(True)
        self.btnDeepExtreme.setCheckable(True)
        self.btnDeepExtreme.setFlat(True)
        self.btnDeepExtreme.setStyleSheet(flatbuttonstyle2)
        self.btnDeepExtreme.setMinimumWidth(ICON_SIZE)
        self.btnDeepExtreme.setMinimumHeight(ICON_SIZE)
        self.btnDeepExtreme.setIcon(QIcon(os.path.join("icons", "dexter.png")))
        self.btnDeepExtreme.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.btnDeepExtreme.setMaximumWidth(BUTTON_SIZE)
        self.btnDeepExtreme.setToolTip("Deep Extreme")
        self.btnDeepExtreme.clicked.connect(self.deepExtreme)

        self.btnApplyClassifier = QPushButton()
        self.btnApplyClassifier.setEnabled(True)
        self.btnApplyClassifier.setCheckable(True)
        self.btnApplyClassifier.setFlat(True)
        self.btnApplyClassifier.setStyleSheet(flatbuttonstyle2)
        self.btnApplyClassifier.setMinimumWidth(ICON_SIZE)
        self.btnApplyClassifier.setMinimumHeight(ICON_SIZE)
        self.btnApplyClassifier.setIcon(QIcon(os.path.join("icons", "auto.png")))
        self.btnApplyClassifier.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.btnApplyClassifier.setMaximumWidth(BUTTON_SIZE)
        self.btnApplyClassifier.setToolTip("Fully automatic calssification")
        self.btnApplyClassifier.clicked.connect(self.applyClassifier)

        self.assignAction = QAction("Assign Class", self)
        self.assignAction.setShortcut(QKeySequence("A"))
        self.assignAction.setShortcutVisibleInContextMenu(True)
        self.assignAction.triggered.connect(self.assign)

        self.deleteAction = QAction("Delete Labels", self)
        self.deleteAction.setShortcut(QKeySequence("Del"))
        self.deleteAction.setShortcutVisibleInContextMenu(True)
        self.deleteAction.triggered.connect(self.deleteSelected)

        self.mergeAction = QAction("Merge Overlapped Labels", self)
        self.mergeAction.setShortcuts(QKeySequence("M"))
        self.mergeAction.setShortcutVisibleInContextMenu(True)
        self.mergeAction.triggered.connect(self.union)

        self.divideAction = QAction("Divide Labels", self)
        self.divideAction.setShortcut(QKeySequence("D"))
        self.divideAction.setShortcutVisibleInContextMenu(True)
        self.divideAction.triggered.connect(self.divide)

        self.subtractAction = QAction("Subtract Labels", self)
        self.subtractAction.setShortcut(QKeySequence("S"))
        self.subtractAction.setShortcutVisibleInContextMenu(True)
        self.subtractAction.triggered.connect(self.subtract)

        self.refineAction = QAction("Refine Border", self)
        self.refineAction.setShortcut(QKeySequence("R"))
        self.refineAction.setShortcutVisibleInContextMenu(True)
        self.refineAction.triggered.connect(self.refineBorder)

        #       in case we want a refine all selected borders
        #        refineActionAll = QAction("Refine All Borders", self)
        #        refineActionAll.setShortcut(QKeySequence("^"))
        #        refineActionAll.setShortcutVisibleInContextMenu(True)
        #        menu.addAction(refineActionAll)
        #            self.refineAllBorders()


        layout_tools.setSpacing(0)
        layout_tools.addWidget(self.btnMove)
        layout_tools.addWidget(self.btnAssign)
        layout_tools.addWidget(self.btnFreehand)
        layout_tools.addWidget(self.btnEditBorder)
        layout_tools.addWidget(self.btnCut)
        layout_tools.addWidget(self.btnCreateCrack)
        layout_tools.addWidget(self.btnRuler)
        layout_tools.addSpacing(10)
        layout_tools.addWidget(self.btnDeepExtreme)
        layout_tools.addWidget(self.btnApplyClassifier)

        layout_tools.addStretch()


        ###### LAYOUT MAIN VIEW

        layout_viewer = QVBoxLayout()

        self.lblSlider = QLabel("Transparency: 0%")

        self.sliderTrasparency = QSlider(Qt.Horizontal)
        self.sliderTrasparency.setFocusPolicy(Qt.StrongFocus)
        self.sliderTrasparency.setMinimumWidth(200)
        self.sliderTrasparency.setStyleSheet(slider_style2)
        self.sliderTrasparency.setMinimum(0)
        self.sliderTrasparency.setMaximum(100)
        self.sliderTrasparency.setValue(0)
        self.sliderTrasparency.setTickInterval(10)
        self.sliderTrasparency.valueChanged.connect(self.sliderTrasparencyChanged)

        self.labelViewInfo = QLabel("100% | top:0 left:0 right:0 bottom:0         ")

        layout_slider = QHBoxLayout()
        layout_slider.addWidget(self.lblSlider)
        layout_slider.addWidget(self.sliderTrasparency)
        layout_slider.addWidget(self.labelViewInfo)

        self.viewerplus = QtImageViewerPlus()
        self.viewerplus.viewUpdated.connect(self.updateViewInfo)

        layout_viewer.setSpacing(1)
        layout_viewer.addLayout(layout_slider)
        layout_viewer.addWidget(self.viewerplus)


        ##### LAYOUT - labels + blob info + navigation map

        # LABELS

        self.labels_widget = LabelsWidget()

        scroll_area = QScrollArea()
        scroll_area.setStyleSheet("background-color: rgb(40,40,40); border:none")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setMinimumHeight(200)
        scroll_area.setWidget(self.labels_widget)

        groupbox_labels = QGroupBox("Labels")

        layout_groupbox = QVBoxLayout()
        layout_groupbox.addWidget(scroll_area)
        groupbox_labels.setLayout(layout_groupbox)

        # BLOB INFO
        groupbox_blobpanel = QGroupBox("Segmentation Info")
        lblInstance = QLabel("Instance Name: ")
        self.editInstance = QLineEdit()
        self.editInstance.setMinimumWidth(80)
        self.editInstance.setMaximumHeight(25)
        self.editInstance.setStyleSheet("background-color: rgb(40,40,40); border: none")
        lblId = QLabel("Id: ")
        self.editId = QLineEdit()
        self.editId.setMinimumWidth(80)
        self.editId.setMaximumHeight(25)
        self.editId.setStyleSheet("background-color: rgb(40,40,40);  border: none")

        blobpanel_layoutH1 = QHBoxLayout()
        blobpanel_layoutH1.addWidget(lblInstance)
        blobpanel_layoutH1.addWidget(self.editInstance)
        blobpanel_layoutH1.addWidget(lblId)
        blobpanel_layoutH1.addWidget(self.editId)

        lblcl = QLabel("Class: ")
        self.lblClass = QLabel("<b>Empty</b>")
        self.lblP = QLabel("Perimeter: ")
        self.lblA = QLabel("Area: ")
        blobpanel_layoutH2 = QHBoxLayout()
        blobpanel_layoutH2.addWidget(lblcl)
        blobpanel_layoutH2.addWidget(self.lblClass)
        blobpanel_layoutH2.addSpacing(6)
        blobpanel_layoutH2.addWidget(self.lblP)
        blobpanel_layoutH2.addWidget(self.lblA)
        blobpanel_layoutH2.addStretch()

        lblNote = QLabel("Note:")
        self.editNote = QTextEdit()
        self.editNote.setMinimumWidth(100)
        self.editNote.setMaximumHeight(50)
        self.editNote.setStyleSheet("background-color: rgb(40,40,40); border: 1px solid rgb(90,90,90)")
        self.editNote.textChanged.connect(self.noteChanged)
        layout_blobpanel = QVBoxLayout()
        layout_blobpanel.addLayout(blobpanel_layoutH1)
        layout_blobpanel.addLayout(blobpanel_layoutH2)
        layout_blobpanel.addWidget(lblNote)
        layout_blobpanel.addWidget(self.editNote)
        groupbox_blobpanel.setLayout(layout_blobpanel)

        # INFO WIDGET

        self.infoWidget = QtInfoWidget(self)

        # MAP VIEWER
        self.mapviewer = QtMapViewer(self.MAP_VIEWER_SIZE)
        self.mapviewer.setImage(None)

        layout_labels = QVBoxLayout()
        self.mapviewer.setStyleSheet("background-color: rgb(40,40,40); border:none")
        layout_labels.addWidget(self.infoWidget)
        layout_labels.addWidget(groupbox_labels)
        layout_labels.addWidget(groupbox_blobpanel)
        layout_labels.addStretch()
        layout_labels.addWidget(self.mapviewer)

        layout_labels.setAlignment(self.mapviewer, Qt.AlignHCenter)

        ##### MAIN LAYOUT

        main_view_layout = QHBoxLayout()
        main_view_layout.addLayout(layout_tools)
        main_view_layout.addLayout(layout_viewer)
        main_view_layout.addLayout(layout_labels)

        main_view_layout.setStretchFactor(layout_viewer, 10)
        main_view_layout.setStretchFactor(layout_labels, 1)

        self.menubar = self.createMenuBar()

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.menubar)
        main_layout.addLayout(main_view_layout)

        self.setLayout(main_layout)

        self.setProjectTitle("NONE")

        ##### FURTHER INITIALIZAION #####
        #################################

        self.map_top = 0
        self.map_left = 0
        self.map_bottom = 0
        self.map_right = 0

        # set default opacity
        self.sliderTrasparency.setValue(50)
        self.transparency_value = 0.5

        self.img_map = None
        self.img_thumb_map = None
        self.img_overlay = QImage(16, 16, QImage.Format_RGB32)

        # EVENTS
        self.labels_widget.visibilityChanged.connect(self.updateVisibility)

        self.mapviewer.leftMouseButtonPressed.connect(self.updateMainView)
        self.mapviewer.mouseMoveLeftPressed.connect(self.updateMainView)

        self.viewerplus.leftMouseButtonPressed.connect(self.toolsOpsLeftPressed)
        self.viewerplus.leftMouseButtonReleased.connect(self.toolsOpsLeftReleased)
        self.viewerplus.rightMouseButtonPressed.connect(self.toolsOpsRightPressed)
        self.viewerplus.mouseMoveLeftPressed.connect(self.toolsOpsMouseMove)
        self.viewerplus.leftMouseButtonDoubleClicked.connect(self.selectOp)

        self.viewerplus.customContextMenuRequested.connect(self.openContextMenu)


        self.current_selection = None

        # DRAWING SETTINGS
        self.border_pen = QPen(Qt.black, 3)
#        pen.setJoinStyle(Qt.MiterJoin)
#        pen.setCapStyle(Qt.RoundCap)
        self.border_pen.setCosmetic(True)
        self.border_selected_pen = QPen(Qt.white, 3)
        self.border_selected_pen.setCosmetic(True)

        self.CROSS_LINE_WIDTH = 6

        # DATA FOR THE SELECTION
        self.selected_blobs = []
        self.MAX_SELECTED = 5 # maximum number of selected blobs

        # DATA FOR THE EDITBORDER , CUT and FREEHAND TOOL
        self.edit_points = []
        self.edit_qpath_gitem = None

        # DATA FOR THE CREATECRACK TOOL
        self.crackWidget = None

        # DATA FOR THE RULER TOOL
        self.ruler_points_number = 0
        self.ruler_points = np.zeros((2, 2))
        self.ruler_lines = []
        self.ruler_text_gi = None

        # DATA FOR THE DEEP EXTREME TOOL
        self.extreme_points_number = 0
        self.extreme_points = np.zeros((4, 2))
        self.extreme_points_lines = []

        # NETWORKS
        self.deepextreme_net = None
        self.corals_classifier = None

        # a dirty trick to adjust all the size..
        self.showMinimized()
        self.showMaximized()

        logfile.info("Inizialization finished!")

        # autosave timer
        self.timer = None

        self.move()


    def activateAutosave(self):

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.autosave)
        self.timer.start(180000)  # save every 3 minute

    @pyqtSlot()
    def autosave(self):

        self.save(self.project_name)

    # call by pressing right button
    def openContextMenu(self, position):

        menu = QMenu(self)
        menu.setAutoFillBackground(True)

        str = "QMenu::item:selected{\
            background-color: rgb(110, 110, 120);\
            color: rgb(255, 255, 255);\
            }"

        menu.setStyleSheet(str)


        menu.addAction(self.assignAction)
        menu.addAction(self.deleteAction)

        menu.addSeparator()

        menu.addAction(self.mergeAction)
        menu.addAction(self.divideAction)
        menu.addAction(self.subtractAction)

        menu.addSeparator()
        menu.addAction(self.refineAction)

        action = menu.exec_(self.viewerplus.mapToGlobal(position))


    def setProjectTitle(self, project_name):

        title = "TagLab - [Project: " + project_name + "]"
        self.setWindowTitle(title)

    def clampCoords(self, x, y):

        xc = int(x)
        yc = int(y)

        if xc < 0:
            xc = 0

        if yc < 0:
            yc = 0

        if xc > self.img_map.width():
            xc = self.img_map.width()

        if yc > self.img_map.height():
            yc = self.img_map.height()

        return (xc, yc)

    def createMenuBar(self):

        newAct = QAction("New Project", self)
        newAct.setShortcut('Ctrl+N')
        newAct.setStatusTip("Create a new project")
        newAct.triggered.connect(self.newProject)

        openAct = QAction("Open Project", self)
        openAct.setShortcut('Ctrl+O')
        openAct.setStatusTip("Open an existing project")
        openAct.triggered.connect(self.openProject)

        saveAct = QAction("Save Project", self)
        saveAct.setShortcut('Ctrl+Alt+S')
        saveAct.setStatusTip("Save current project")
        saveAct.triggered.connect(self.saveProject)

        # THIS WILL BECOME "ADD MAP" TO ADD MULTIPLE MAPS (e.g. depth, different years)
        loadMapAct = QAction("Load Map", self)
        loadMapAct.setShortcut('Ctrl+L')
        loadMapAct.setStatusTip("Set and load a map")
        loadMapAct.triggered.connect(self.setMapToLoad)

        importAct = QAction("Import Label Map", self)
        importAct.setStatusTip("Import a label map")
        importAct.triggered.connect(self.importLabelMap)

        exportAct = QAction("Export Data", self)
        #exportAct.setShortcut('Ctrl+Q')
        exportAct.setStatusTip("Export data derived from annotations")
        exportAct.triggered.connect(self.exportData)

        undoAct = QAction("Undo", self)
        undoAct.setShortcut('Ctrl+Z')
        undoAct.setStatusTip("Undo")
        undoAct.triggered.connect(self.undo)

        helpAct = QAction("Help", self)
        #exportAct.setShortcut('Ctrl+Q')
        #helpAct.setStatusTip("Help")
        helpAct.triggered.connect(self.help)

        aboutAct = QAction("About", self)
        #exportAct.setShortcut('Ctrl+Q')
        #aboutAct.setStatusTip("About")
        aboutAct.triggered.connect(self.about)

        menubar = QMenuBar()
        menubar.setAutoFillBackground(True)

        styleMenuBar = "QMenuBar::item:selected{\
            background-color: rgb(110, 110, 120);\
            color: rgb(255, 255, 255);\
            }"

        styleMenu = "QMenu::item:selected{\
            background-color: rgb(110, 110, 120);\
            color: rgb(255, 255, 255);\
            }"

        menubar.setStyleSheet(styleMenuBar)

        filemenu = menubar.addMenu("&File")
        filemenu.setStyleSheet(styleMenu)
        filemenu.addAction(newAct)
        filemenu.addAction(openAct)
        filemenu.addAction(saveAct)
        filemenu.addSeparator()
        filemenu.addAction(loadMapAct)
        filemenu.addSeparator()
        filemenu.addAction(importAct)
        filemenu.addAction(exportAct)

        editmenu = menubar.addMenu("&Edit")
        editmenu.addAction(undoAct)
        editmenu.addSeparator()

        editmenu.addAction(self.assignAction)
        editmenu.addAction(self.deleteAction)

        editmenu.addSeparator()

        editmenu.addAction(self.mergeAction)
        editmenu.addAction(self.divideAction)
        editmenu.addAction(self.subtractAction)

        editmenu.addSeparator()
        editmenu.addAction(self.refineAction)

        helpmenu = menubar.addMenu("&Help")
        helpmenu.setStyleSheet(styleMenu)
        helpmenu.addAction(helpAct)
        helpmenu.addAction(aboutAct)

        return menubar

    def keyPressEvent(self, event):

        key_pressed = event.text()
        str = "Key '" + key_pressed + "' has been pressed."
        logfile.info(str)

        modifiers = QApplication.queryKeyboardModifiers()

        if event.key() == Qt.Key_Escape:
            # RESET CURRENT OPERATION
            self.resetSelection()
            if self.tool_used in ["EDITBORDER", "CUT", "FREEHAND"]:
                self.resetEditBorder()
            elif self.tool_used == "RULER":
                self.resetRulerTool()
            elif self.tool_used == "DEEPEXTREME":
                self.resetDeepExtremeTool()
            elif self.tool_used == "AUTOCLASS":
                self.corals_classifier.stopProcessing()

            self.tool_used = self.tool_orig

        elif event.key() == Qt.Key_S and modifiers == Qt.ControlModifier:
            self.save(self.project_name)
        elif event.key() == Qt.Key_Delete:
            # DELETE SELECTED BLOBS
            self.deleteSelected()
        elif event.key() == Qt.Key_M:
            # MERGE BETWEEN TWO BLOBS
            self.union()
        elif event.key() == Qt.Key_S:
            # SUBTRACTION BETWEEN TWO BLOBS (A = A / B), THEN BLOB B IS DELETED
            self.subtract()
        elif event.key() == Qt.Key_D:
            # SUBTRACTION BETWEEN TWO BLOBS (A = A / B), BLOB B IS NOT DELETED
            self.divide()
        elif event.key() == Qt.Key_R:
            # REFINE BORDER
            self.refineBorder()
        elif event.key() == Qt.Key_G:
            # GROUP TOGETHER THE SELECTED BLOBS
            self.group()
        elif event.key() == Qt.Key_U:
            # UNGROUP THE BLOBS OF A GROUP (ONE BLOB OF THE GROUP SHOULD BE SELECTED)
            self.ungroup()
        elif event.key() == Qt.Key_A:
            # ACTIVATE "ASSIGN" TOOL
            self.assign()
        elif event.key() == Qt.Key_H:
            # ACTIVATE THE "HOLE" TOOL
            self.hole()
        elif event.key() == Qt.Key_4:
            # ACTIVATE "DEEP EXTREME" TOOL
            self.deepExtreme()
        elif event.key() == Qt.Key_P:
            self.drawDeepExtremePoints()
        elif event.key() == Qt.Key_X:
            self.applyClassifier()
        elif event.key() == Qt.Key_Space:

            #drawing operations are grouped
            if self.tool_used in ["EDITBORDER", "CUT", "FREEHAND"]:
                if len(self.edit_points) == 0:
                    self.infoWidget.setInfoMessage("You need to draw something for this operation.")
                    return


                if self.tool_used == "FREEHAND":
                    blob = Blob(None, 0, 0, 0)

                    flagValid = blob.createFromClosedCurve(self.edit_points)

                    if flagValid is True:
                        logfile.info("FREEHAND operation ends.")

                        id = len(self.annotations.seg_blobs)
                        blob.setId(id + 1)

                        self.resetSelection()
                        self.addBlob(blob, selected=True)
                        self.saveUndo()
                    else:
                        logfile.info("FREEHAND operation not done (invalid snap).")

                #editborder and cut require a selected area
                if self.tool_used in ["EDITBORDER", "CUT"]:
                    if len(self.selected_blobs) != 1:
                        self.infoWidget.setInfoMessage("A single selected area is required.")
                        return

                    selected_blob = self.selected_blobs[0]

                if self.tool_used == "EDITBORDER":
                    blob = selected_blob.copy()

                    self.annotations.editBorder(blob, self.edit_points)
                    self.removeBlob(selected_blob)
                    self.addBlob(blob, selected=True)
                    self.saveUndo()

                if self.tool_used == "CUT":
                    created_blobs = self.annotations.cut(selected_blob, self.edit_points)

                    for blob in created_blobs:
                        self.addBlob(blob, selected=True)
                    self.removeBlob(selected_blob)
                    self.saveUndo()

                self.resetEditBorder()

            # APPLY DEEP EXTREME (IF FOUR POINTS HAVE BEEN SELECTED)
            elif self.tool_used == "DEEPEXTREME" and self.extreme_points_number == 4:

                self.segmentWithDeepExtreme()
                self.resetDeepExtremeTool()

            self.tool_used = self.tool_orig


    @pyqtSlot()
    def sliderTrasparencyChanged(self):

        # update transparency value
        newvalue = self.sliderTrasparency.value()
        str1 = "Transparency {}%".format(newvalue)
        self.lblSlider.setText(str1)
        self.transparency_value = self.sliderTrasparency.value() / 100.0

        # update transparency of all the blobs
        self.applyTransparency()

    def applyTransparency(self):

        for blob in self.annotations.seg_blobs:
            blob.qpath_gitem.setOpacity(self.transparency_value)

    @pyqtSlot()
    def updateVisibility(self):

        for blob in self.annotations.seg_blobs:

            visibility = self.labels_widget.isClassVisible(blob.class_name)
            blob.qpath_gitem.setVisible(visibility)


    @pyqtSlot()
    def updateViewInfo(self):

        zf = self.viewerplus.zoom_factor * 100.0

        topleft = self.viewerplus.mapToScene(QPoint(0, 0))
        bottomright = self.viewerplus.mapToScene(self.viewerplus.viewport().rect().bottomRight())

        (left, top) = self.clampCoords(topleft.x(), topleft.y())
        (right, bottom) = self.clampCoords(bottomright.x(), bottomright.y())

        text = "| {:6.2f}% | top: {:4d} left: {:4d} bottom: {:4d} right: {:4d}".format(zf, top, left, bottom, right)

        self.map_top = top
        self.map_left = left
        self.map_bottom = bottom
        self.map_right = right

        self.labelViewInfo.setText(text)

    @pyqtSlot(float, float)
    def updateMainView(self, x, y):

        zf = self.viewerplus.zoom_factor

        xmap = float(self.img_map.width()) * x
        ymap = float(self.img_map.height()) * y

        h = self.map_bottom - self.map_top
        w = self.map_right - self.map_left

        posx = xmap - w / 2
        posy = ymap - h / 2

        if posx < 0:
            posx = 0
        if posy < 0:
            posy = 0

        if posx + w/2 > self.img_map.width():
            posx = self.img_map.width() - w / 2 - 1

        if posy + h/2 > self.img_map.height():
            posy = self.img_map.height() - h / 2 - 1

        posx = posx * zf;
        posy = posy * zf;

        self.viewerplus.horizontalScrollBar().setValue(posx)
        self.viewerplus.verticalScrollBar().setValue(posy)

    @pyqtSlot()
    def updateMapViewer(self):

        topleft = self.viewerplus.mapToScene(QPoint(0, 0))
        bottomright = self.viewerplus.mapToScene(self.viewerplus.viewport().rect().bottomRight())

        W = float(self.img_map.width())
        H = float(self.img_map.height())

        top = float(topleft.y()) / H
        left = float(topleft.x()) / W
        bottom = float(bottomright.y()) / H
        right = float(bottomright.x()) / W

        self.mapviewer.drawOverlayImage(top, left, bottom, right)

    def resetAll(self):

        if self.img_map is not None:
            del self.img_map
            self.img_map = None

        if self.img_thumb_map is not None:
            del self.img_thumb_map
            self.img_thumb_map = None

        if self.annotations:
            del self.annotations

        self.annotations = Annotation()

        # RE-INITIALIZATION
        self.mapWidget = None
        self.project_name = "NONE"
        self.map_image_filename = "map.png"
        self.map_acquisition_date = "YYYY-MM-DD"
        self.map_px_to_mm_factor = 1.0


    def resetToolbar(self):

        self.btnMove.setChecked(False)
        self.btnAssign.setChecked(False)
        self.btnEditBorder.setChecked(False)
        self.btnCut.setChecked(False)
        self.btnFreehand.setChecked(False)
        self.btnRuler.setChecked(False)
        self.btnCreateCrack.setChecked(False)

        self.btnDeepExtreme.setChecked(False)

    @pyqtSlot()
    def move(self):
        """
        Activate the tool "move".
        """

        self.resetToolbar()
        self.resetTools()

        self.btnMove.setChecked(True)
        self.tool_used = self.tool_orig = "MOVE"

        self.viewerplus.enablePan()
        self.viewerplus.enableZoom()

        self.infoWidget.setInfoMessage("Move Tool is active")
        logfile.info("MOVE tool is active")


    @pyqtSlot()
    def createCrack(self):
        """
        Activate the tool "Create Crack".
        """

        self.resetToolbar()
        self.resetTools()

        self.btnCreateCrack.setChecked(True)
        self.tool_used = self.tool_orig = "CREATECRACK"

        self.viewerplus.enablePan()
        self.viewerplus.enableZoom()

        self.infoWidget.setInfoMessage("Crack Tool is active")
        logfile.info("CREATECRACK tool is active")


    @pyqtSlot(float, float)
    def selectOp(self, x, y):
        """
        Selection operation.
        """

        # NOTE: double click selection is disabled with ASSIGN, RULER and DEEPEXTREME tools

        if self.tool_used == "ASSIGN" or self.tool_used == "RULER" or self.tool_used == "DEEPEXTREME":
            return

        modifiers = QApplication.queryKeyboardModifiers()
        if not (modifiers & Qt.ShiftModifier):
            self.resetSelection()

        selected_blob = self.annotations.clickedBlob(x, y)

        if selected_blob:

            if selected_blob in self.selected_blobs:
                self.removeFromSelectedList(selected_blob)
            else:
                self.addToSelectedList(selected_blob)
                self.updatePanelInfo(selected_blob)


    @pyqtSlot()
    def assign(self):
        """
        Activate the tool "Assign" to assign a class to an existing blob.
        """

        self.resetToolbar()
        self.resetTools()

        self.btnAssign.setChecked(True)
        self.tool_used = self.tool_orig = "ASSIGN"

        self.viewerplus.disablePan()
        self.viewerplus.enableZoom()

        self.infoWidget.setInfoMessage("Assign Tool is active")
        logfile.info("ASSIGN tool is active")

    @pyqtSlot()
    def editBorder(self):
        """
        Activate the tool "EDITBORDER" for pixel-level editing operations.
        NOTE: it works one blob at a time (!)
        """

        self.resetToolbar()
        self.resetTools()

        if len(self.selected_blobs) > 1:
            self.resetSelection()

        self.btnEditBorder.setChecked(True)
        self.tool_used = self.tool_orig = "EDITBORDER"

        self.viewerplus.disablePan()
        self.viewerplus.enableZoom()

        self.infoWidget.setInfoMessage("Edit Border Tool is active")
        logfile.info("EDITBORDER tool is active")

    @pyqtSlot()
    def cut(self):
        """
        CUT
        """
        self.resetToolbar()
        self.resetTools()

        if len(self.selected_blobs) > 1:
            self.resetSelection()

        self.btnCut.setChecked(True)
        self.tool_used = self.tool_orig = "CUT"

        self.edit_qpath_gitem = self.viewerplus.scene.addPath(QPainterPath(), self.border_pen)

        self.viewerplus.disablePan()
        self.viewerplus.enableZoom()

        logfile.info("CUT tool is active")

    @pyqtSlot()
    def freehandSegmentation(self):
        """
        Activate the tool "FREEHAND" for manual segmentation.
        """

        self.resetToolbar()
        self.resetTools()
        self.resetSelection()

        self.btnFreehand.setChecked(True)
        self.tool_used = self.tool_orig = "FREEHAND"

        self.edit_qpath_gitem = self.viewerplus.scene.addPath(QPainterPath(), self.border_pen)

        self.viewerplus.disablePan()
        self.viewerplus.enableZoom()

        self.infoWidget.setInfoMessage("Freehand Tool is active")
        logfile.info("FREEHAND tool is active")

    @pyqtSlot()
    def ruler(self):
        """
        Activate the "ruler" tool. The tool allows to measure the distance between two points or between two blob centroids.
        """

        self.resetToolbar()
        self.resetTools()

        self.resetSelection()

        self.btnRuler.setChecked(True)
        self.tool_used = self.tool_orig = "RULER"

        self.viewerplus.disablePan()
        self.viewerplus.enableZoom()

        self.infoWidget.setInfoMessage("Ruler Tool is active")
        logfile.info("RULER tool is active")

    @pyqtSlot()
    def hole(self):
        pass

    @pyqtSlot()
    def deepExtreme(self):
        """
        Activate the "Deep Extreme" tool. The segmentation is performed by selecting four points at the
        extreme of the corals and confirm the points by pressing SPACE.
        """

        self.resetToolbar()
        self.resetTools()
        self.resetSelection()

        if self.deepextreme_net is None:
            self.resetNetworks()
            self.infoWidget.setInfoMessage("Loading deepextreme network..")
            self.loadingDeepExtremeNetwork()

        self.btnDeepExtreme.setChecked(True)
        self.tool_used = self.tool_orig = "DEEPEXTREME"

        self.viewerplus.showCrossair = True

        self.viewerplus.disablePan()
        self.viewerplus.enableZoom()

        self.infoWidget.setInfoMessage("4-click tool is active")
        logfile.info("DEEPEXTREME tool is active")


    def addToSelectedList(self, blob):
        """
        Add the given blob to the list of selected blob.
        """

        if blob in self.selected_blobs:
            logfile.info("An already selected blob has been added to the current selection.")
        else:
            self.selected_blobs.append(blob)
            str = "A new blob (" + blob.blob_name + ") has been selected."
            logfile.info(str)

        if not blob.qpath_gitem is None:
            blob.qpath_gitem.setPen(self.border_selected_pen)
        self.viewerplus.scene.invalidate()


    def removeFromSelectedList(self, blob):
        try:
            #safer if iterting over selected_blobs and calling this function.
            self.selected_blobs = [x for x in self.selected_blobs if not x == blob]
            if not blob.qpath_gitem is None:
                blob.qpath_gitem.setPen(self.border_pen)
            self.viewerplus.scene.invalidate()
        except:
            pass


    @pyqtSlot()
    def noteChanged(self):

        if len(self.selected_blobs) > 0:

            for blob in self.selected_blobs:
                blob.note = self.editNote.toPlainText()

    def updatePanelInfo(self, blob):

        self.editId.setText(blob.blob_name)
        self.editInstance.setText(blob.instance_name)
        self.lblClass.setText(blob.class_name)

        text1 = "Perimeter {:8.2f}".format(blob.perimeter)
        self.lblP.setText(text1)

        text2 = "Area: {:8.2f}".format(blob.area)
        self.lblA.setText(text2)

        self.editNote.setPlainText(blob.note)


    def deleteSelected(self):

        for blob in self.selected_blobs:
            self.removeBlob(blob)
        self.saveUndo()

        logfile.info("Selected blobs has been DELETED")

    def isSelected(self, target_blob):
        """
        Check if a blob belongs to the selected blobs.
        """

        blobs_to_check = set()
        for blob in self.selected_blobs:
            if blob.group:
                for blobg in blob.group.blobs:
                    blobs_to_check.add(blobg)
            else:
                blobs_to_check.add(blob)

        for blob in blobs_to_check:
            if blob == target_blob:
                return True

        return False


    def drawDeepExtremePoints(self):

        pen = QPen(Qt.blue)
        pen.setWidth(self.CROSS_LINE_WIDTH)
        brush = QBrush(Qt.SolidPattern)
        brush.setColor(Qt.blue)

        X_SIZE = 12

        for blob in self.annotations.seg_blobs:

            ptx = blob.deep_extreme_points[0, 0]
            pty = blob.deep_extreme_points[0, 1]

            line1 = self.viewerplus.scene.addLine(ptx - X_SIZE, pty - X_SIZE, ptx + X_SIZE, pty + X_SIZE, pen)
            line2 = self.viewerplus.scene.addLine(ptx - X_SIZE, pty + X_SIZE, ptx + X_SIZE, pty - X_SIZE, pen)

            ptx = blob.deep_extreme_points[1, 0]
            pty = blob.deep_extreme_points[1, 1]

            line3 = self.viewerplus.scene.addLine(ptx - X_SIZE, pty - X_SIZE, ptx + X_SIZE, pty + X_SIZE, pen)
            line4 = self.viewerplus.scene.addLine(ptx - X_SIZE, pty + X_SIZE, ptx + X_SIZE, pty - X_SIZE, pen)

            ptx = blob.deep_extreme_points[2, 0]
            pty = blob.deep_extreme_points[2, 1]

            line5 = self.viewerplus.scene.addLine(ptx - X_SIZE, pty - X_SIZE, ptx + X_SIZE, pty + X_SIZE, pen)
            line6 = self.viewerplus.scene.addLine(ptx - X_SIZE, pty + X_SIZE, ptx + X_SIZE, pty - X_SIZE, pen)

            ptx = blob.deep_extreme_points[3, 0]
            pty = blob.deep_extreme_points[3, 1]

            line7 = self.viewerplus.scene.addLine(ptx - X_SIZE, pty - X_SIZE, ptx + X_SIZE, pty + X_SIZE, pen)
            line8 = self.viewerplus.scene.addLine(ptx - X_SIZE, pty + X_SIZE, ptx + X_SIZE, pty - X_SIZE, pen)

    def drawGroup(self, group):
        raise Exception('SHOLD NEVER BE CALLED!')
        """
        Draw all the blobs of the group with a darkGray border.
        """
        for blob in group.blobs:
            self.drawBlob(blob, selected=False, group_mode=True)

    def drawSelectedBlobs(self):
        raise Exception('SHOLD NEVER BE CALLED!')
        """
        Draw all the selected blobs with a white border.
        If a selected blob belongs to a group, the group is highlight using darkGray.
        """

        for blob in self.selected_blobs:
            if blob.group is not None:
                self.drawGroup(blob.group)

        for blob in self.selected_blobs:
            self.drawBlob(blob, selected=True)

    def drawBlob(self, blob):
        """
        Draw a blob according to the class color. If the blob is selected a white border is used.
        Note that if group_mode == True the blob is drawn in darkGray
        and the selection flag is ignored.
        """

        # if it has just been created remove the current graphics item in order to set it again
        if blob.qpath_gitem is not None:
            self.viewerplus.scene.removeItem(blob.qpath_gitem)
            del blob.qpath_gitem
            blob.qpath_gitem = None

        blob.setupForDrawing()

        pen = self.border_selected_pen if blob in self.selected_blobs else self.border_pen
        brush = self.classBrushFromName(blob)

        blob.qpath_gitem = self.viewerplus.scene.addPath(blob.qpath, pen, brush)
        blob.qpath_gitem.setOpacity(self.transparency_value)

    def classBrushFromName(self, blob):
        brush = QBrush()

        if not blob.class_name == "Empty":
            color = self.labels_widget.labels.getColorByName(blob.class_name)
            brush = QBrush(QColor(color[0], color[1], color[2], 200))
        return brush



    def undrawBlob(self, blob):

        self.viewerplus.scene.removeItem(blob.qpath_gitem)
        del blob.qpath
        blob.qpath = None
        del blob.qpath_gitem  # QGraphicsScene does not delete the item
        blob.qpath_gitem = None
        self.viewerplus.scene.invalidate()

    def drawRuler(self):

        if self.ruler_points_number > 0:

            for line in self.ruler_lines:
                self.viewerplus.scene.removeItem(line)

            if self.ruler_text_gi:
                self.viewerplus.scene.removeItem(self.ruler_text_gi)

            pen = QPen(Qt.blue)
            pen.setWidth(self.CROSS_LINE_WIDTH)
            brush = QBrush(Qt.SolidPattern)
            brush.setColor(Qt.blue)

            X_SIZE = 12

            measure = 0.0
            if self.ruler_points_number == 2:
                measure = self.computeMeasure()

            if self.ruler_points_number == 1:

                x = self.ruler_points[0, 0]
                y = self.ruler_points[0, 1]

                line1 = self.viewerplus.scene.addLine(x - X_SIZE, y - X_SIZE, x + X_SIZE, y + X_SIZE, pen)
                line2 = self.viewerplus.scene.addLine(x - X_SIZE, y + X_SIZE, x + X_SIZE, y - X_SIZE, pen)
                self.ruler_lines.append(line1)
                self.ruler_lines.append(line2)

            if self.ruler_points_number == 2:

                x = self.ruler_points[0, 0]
                y = self.ruler_points[0, 1]

                line1 = self.viewerplus.scene.addLine(x - X_SIZE, y - X_SIZE, x + X_SIZE, y + X_SIZE, pen)
                line2 = self.viewerplus.scene.addLine(x - X_SIZE, y + X_SIZE, x + X_SIZE, y - X_SIZE, pen)
                self.ruler_lines.append(line1)
                self.ruler_lines.append(line2)

                x = self.ruler_points[1, 0]
                y = self.ruler_points[1, 1]

                line3 = self.viewerplus.scene.addLine(x - X_SIZE, y - X_SIZE, x + X_SIZE, y + X_SIZE, pen)
                line4 = self.viewerplus.scene.addLine(x - X_SIZE, y + X_SIZE, x + X_SIZE, y - X_SIZE, pen)
                self.ruler_lines.append(line3)
                self.ruler_lines.append(line4)

                pen.setWidth(4)
                line3 = self.viewerplus.scene.addLine(self.ruler_points[0, 0], self.ruler_points[0, 1],
                                                      self.ruler_points[1, 0],
                                                      self.ruler_points[1, 1], pen)
                self.ruler_lines.append(line3)

                posx = (self.ruler_points[1, 0] + self.ruler_points[0, 0]) / 2.0
                posy = (self.ruler_points[1, 1] + self.ruler_points[0, 1]) / 2.0

                myfont = QFont("Times", 18, QFont.Bold)
                self.ruler_text_gi = self.viewerplus.scene.addText('%.4f' % measure)
                self.ruler_text_gi.setFont(myfont)
                self.ruler_text_gi.setDefaultTextColor(Qt.white)
                self.ruler_text_gi.setPos(posx, posy)




    def union(self):
        """
        blob A = blob A U blob B
        """

        logfile.info("MERGE OVERLAPPED LABELS operation")
        logfile.debug("Number of selected blobs: %d", len(self.selected_blobs))

        if len(self.selected_blobs) > 1:

            logfile.info("MERGE OVERLAPPED LABELS operation begins..")

            #union returns a NEW blob
            union_blob = self.annotations.union(self.selected_blobs)

            if union_blob is None:
                logfile.debug("Blobs are separated. MERGE OVERLAPPED LABELS operation not applied.")
            else:
                for blob in self.selected_blobs:
                    self.removeBlob(blob)
                self.addBlob(union_blob, selected=True)
                self.saveUndo()


            logfile.info("MERGE OVERLAPPED LABELS operation ends.")

        else:
            self.infoWidget.setWarningMessage("You need to select at least <em>two</em> blobs for MERGE OVERLAPPED LABELS operation.")


    def subtract(self):
        """
        blob A = blob A / blob B
        """

        logfile.info("SUBTRACT LABELS operation")
        logfile.debug("Number of selected blobs: %d", len(self.selected_blobs))

        if len(self.selected_blobs) == 2:

            logfile.info("SUBTRACT LABELS operation begins..")


            selectedA = self.selected_blobs[0]
            selectedB = self.selected_blobs[1]

            #blobA and will be modified, make a copy!
            blobA = selectedA.copy()

            flag_intersection = self.annotations.subtract(blobA, selectedB, self.viewerplus.scene)

            if flag_intersection:
                self.removeBlob(selectedA)
                self.removeBlob(selectedB)
                self.addBlob(blobA, selected=True)
                self.saveUndo()

            logfile.info("SUBTRACT LABELS operation ends.")

        else:

            self.infoWidget.setInfoMessage("You need to select <em>two</em> blobs for SUBTRACT operation.")


    def divide(self):
        """
        Separe intersecting blob
        """

        logfile.info("DIVIDE LABELS operation")
        logfile.debug("Number of selected blobs: %d", len(self.selected_blobs))

        if len(self.selected_blobs) == 2:

            logfile.info("DIVIDE LABELS operation begins..")

            selectedA = self.selected_blobs[0]
            selectedB = self.selected_blobs[1]

            #blobA and blobB and will be modified, make a copy!
            blobA = selectedA.copy()
            blobB = selectedB.copy()

            intersects = self.annotations.subtract(blobB, blobA, self.viewerplus.scene)
            if intersects:
                self.removeBlob(selectedA)
                self.removeBlob(selectedB)
                self.addBlob(blobA, selected=False)
                self.addBlob(blobB, selected=False)
                self.saveUndo()

            logfile.info("DIVIDE LABELS operation ends.")

        else:

            self.infoWidget.setInfoMessage("You need to select <em>two</em> blobs for DIVIDE operation.")

    def refineBorder(self):
        """
        Refine blob border
        """

        logfile.info("REFINE BORDER operation")
        logfile.debug("Number of selected blobs: %d", len(self.selected_blobs))

        # padding mask to allow moving boundary
        padding = 30
        if len(self.selected_blobs) == 1:

            logfile.info("REFINE BORDER operation begins..")

            selected = self.selected_blobs[0]
            blob = selected.copy()

            mask = blob.getMask()
            mask = np.pad(mask, (padding, padding), mode='constant', constant_values=(0, 0)).astype(np.ubyte)

            bbox = blob.bbox.copy()
            bbox[0] -= padding; #top
            bbox[1] -= padding; #left
            bbox[2] += 2*padding; #width
            bbox[3] += 2*padding; #height

            img = utils.cropQImage(self.img_map, bbox);
            try:
                from coraline.Coraline import segment
                segment(utils.qimageToNumpyArray(img), mask, 0.0, 1.0)

            except Exception as e:
                msgBox = QMessageBox()
                msgBox.setText(str(e))
                msgBox.exec()
                return


            blob.updateUsingMask(bbox, mask.astype(np.int))
            self.removeBlob(selected)
            self.addBlob(blob, selected=True)
            self.saveUndo()

            logfile.info("REFINE BORDER operation ends.")

        else:
            self.infoWidget.setInfoMessage("You need to select <em>one</em> blob for REFINE operation.")


    def addBlob(self, blob, selected = False):
        """
        The only function to add annotations. will take care of undo and QGraphicItems.
        """
        self.undo_operation['remove'].append(blob)
        self.annotations.addBlob(blob)
        self.drawBlob(blob)
        if selected:
            self.addToSelectedList(blob)

    def removeBlob(self, blob):
        """
        The only function to remove annotations.
        """
        self.removeFromSelectedList(blob)
        self.undrawBlob(blob)
        self.undo_operation['add'].append(blob)
        self.annotations.removeBlob(blob)

    def setBlobClass(self, blob, class_name):
        if blob.class_name == class_name:
            return

        self.undo_operation['class'].append((blob, blob.class_name))
        blob.class_name = class_name
        blob.class_color = self.labels_widget.labels.getColorByName(blob.class_name)

        brush = self.classBrushFromName(blob)
        blob.qpath_gitem.setBrush(brush)

        self.viewerplus.scene.invalidate()

    def saveUndo(self):
        """
        Will mark an undo step using the previosly added and removed blobs.
        """
        if len(self.undo_operation['add']) == 0 and len(self.undo_operation['remove']) == 0 and len(self.undo_operation['class']) == 0:
            return

        self.undo_operations.append(self.undo_operation)
        self.undo_operation = { 'remove':[], 'add':[], 'class':[] }
        if len(self.undo_operations) > self.max_undo:
            self.undo_operations.pop(0)

    def undo(self):
        if len(self.undo_operations) is 0:
            return

        operation = self.undo_operations.pop(-1)
        for blob in operation['remove']:
            self.removeFromSelectedList(blob)
            self.undrawBlob(blob)
            self.annotations.removeBlob(blob)

        for blob in operation['add']:
            self.annotations.addBlob(blob)
            self.selected_blobs.append(blob)
            self.drawBlob(blob)

        for (blob, class_name) in operation['class']:
            blob.class_name = class_name
            brush = self.classBrushFromName(blob)
            blob.qpath_gitem.setBrush(brush)

        self.updateVisibility()

    def group(self):

        if len(self.selected_blobs) > 0:

            group = self.annotations.addGroup(self.selected_blobs)
            self.drawGroup(group)

    def ungroup(self):

        if len(self.selected_blobs) > 0:

            blob_s = self.selected_blobs[0]

            if blob_s.group != None:

                # de-selection
                for blob in self.selected_blobs:
                    self.drawBlob(blob, selected=False)
                self.selected_blobs.clear()

                self.annotations.removeGroup(blob_s.group)

    def resetSelection(self):

        for blob in self.selected_blobs:
            blob.qpath_gitem.setPen(self.border_pen)

        self.selected_blobs.clear()
        self.viewerplus.scene.invalidate(self.viewerplus.scene.sceneRect())

    def resetEditBorder(self):

        if self.edit_qpath_gitem is not None:
            self.edit_qpath_gitem.setPath(QPainterPath())
        else:
            self.edit_qpath = None

        self.edit_points = []

    def resetCrackTool(self):

        if self.crackWidget is not None:
            self.crackWidget.close()

        self.crackWidget = None

        # panning of the crack preview cause some problems..
        self.viewerplus.setDragMode(QGraphicsView.NoDrag)


    def resetRulerTool(self):

        for line in self.ruler_lines:
            self.viewerplus.scene.removeItem(line)

        if self.ruler_text_gi:
            self.viewerplus.scene.removeItem(self.ruler_text_gi)

        self.ruler_points = np.zeros((2, 2))

        self.ruler_points_number = 0
        self.ruler_points = np.zeros((2, 2))


    def resetDeepExtremeTool(self):

        for line in self.extreme_points_lines:
            self.viewerplus.scene.removeItem(line)

        self.extreme_points_lines.clear()
        self.extreme_points_number = 0
        self.extreme_points = np.zeros((4, 2))


    def resetTools(self):

        self.resetEditBorder()
        self.resetCrackTool()
        self.resetRulerTool()
        self.resetDeepExtremeTool()

        self.viewerplus.showCrossair = False
        self.viewerplus.scene.invalidate(self.viewerplus.scene.sceneRect())


    @pyqtSlot(float, float)
    def toolsOpsLeftPressed(self, x, y):

        modifiers = QApplication.queryKeyboardModifiers()
        if modifiers & Qt.ControlModifier:
            return

        if (modifiers & Qt.ShiftModifier) and self.tool_used == "FREEHAND":
            self.tool_used = "EDITBORDER"

        if self.tool_used == "ASSIGN":

            selected_blob = self.annotations.clickedBlob(x, y)

            if selected_blob is not None:
                self.addToSelectedList(selected_blob)
                for blob in self.selected_blobs:
                    self.setBlobClass(blob, self.labels_widget.getActiveLabelName())
                self.saveUndo()

                self.resetSelection()

        elif self.tool_used in ["EDITBORDER", "CUT", "FREEHAND"]:

            logfile.info("DRAWING")

            if len(self.edit_points) == 0: #first point, initialize
                self.edit_qpath_gitem = self.viewerplus.scene.addPath(QPainterPath(), self.border_pen)


            self.edit_points.append(np.array([[x, y]]))

            path = self.edit_qpath_gitem.path()
            path.moveTo(QPointF(x, y))
            self.edit_qpath_gitem.setPath(path)
            self.viewerplus.scene.invalidate()

            logfile.debug("Number of DRAWING paths: %d", len(self.edit_points))

        elif self.tool_used == "CREATECRACK":

            selected_blob = self.annotations.clickedBlob(x, y)

            if selected_blob is not None:

                self.resetSelection()
                self.addToSelectedList(selected_blob)

                xpos = self.viewerplus.clicked_x
                ypos = self.viewerplus.clicked_y

                if self.crackWidget is None:

                    logfile.info("CREATECRACK tool active")

                    #copy blob, for undo reasons.
                    blob = selected_blob.copy()

                    self.crackWidget = QtCrackWidget(self.img_map, blob, x, y, parent=self)
                    self.crackWidget.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
                    self.crackWidget.setWindowModality(Qt.WindowModal)
                    self.crackWidget.btnCancel.clicked.connect(self.crackCancel)
                    self.crackWidget.btnApply.clicked.connect(self.crackApply)
                    self.crackWidget.closeCrackWidget.connect(self.crackCancel)
                    self.crackWidget.show()

        elif self.tool_used == "RULER":

            if self.ruler_points_number < 2:

                ind = self.ruler_points_number
                self.ruler_points[ind, 0] = x
                self.ruler_points[ind, 1] = y
                self.ruler_points_number += 1

                self.drawRuler()

            else:

                self.resetRulerTool()

        elif self.tool_used == "DEEPEXTREME":

            if self.extreme_points_number < 4:

                ind = self.extreme_points_number
                self.extreme_points[ind, 0] = x
                self.extreme_points[ind, 1] = y
                self.extreme_points_number += 1

                pen = QPen(Qt.red)
                pen.setWidth(self.CROSS_LINE_WIDTH)
                pen.setCosmetic(True)
                brush = QBrush(Qt.SolidPattern)
                brush.setColor(Qt.red)

                X_SIZE = 12
                line1 = self.viewerplus.scene.addLine(x - X_SIZE, y - X_SIZE, x + X_SIZE, y + X_SIZE, pen)
                line2 = self.viewerplus.scene.addLine(x - X_SIZE, y + X_SIZE, x + X_SIZE, y - X_SIZE, pen)
                self.extreme_points_lines.append(line1)
                self.extreme_points_lines.append(line2)

            elif self.extreme_points_number > 3:

                self.resetDeepExtremeTool()

    @pyqtSlot(float, float)
    def toolsOpsLeftReleased(self, x, y):
        pass

    @pyqtSlot(float, float)
    def toolsOpsRightPressed(self, x, y):
        pass

    @pyqtSlot(float, float)
    def toolsOpsMouseMove(self, x, y):

        modifiers = QApplication.queryKeyboardModifiers()
        if modifiers & Qt.ControlModifier:
            return

        if self.tool_used in ["EDITBORDER", "CUT", "FREEHAND"]:

            logfile.info("DRAWING")
            #check that a move didn't happen before a press
            last = self.edit_points[-1]
            #if len(self.edit_points) > 0 and last.shape[0] > 0:

            self.edit_points[-1] = np.append(last, [[x, y]], axis=0)
            path = self.edit_qpath_gitem.path()
            path.lineTo(QPointF(x, y))
            self.edit_qpath_gitem.setPath(path)
            self.viewerplus.scene.invalidate()

            logfile.debug("Number of DRAWING points: %d", last.shape[0])




    @pyqtSlot()
    def crackCancel(self):

        self.resetCrackTool()

    @pyqtSlot()
    def crackApply(self):

        self.crackWidget.apply()
        self.removeBlob(self.selected_blobs[0])
        self.addBlob(self.crackWidget.blob, selected=True)
        self.saveUndo()

        logfile.info("CREATECRACK creates a crack.")

        #self.drawBlob(self.selected_blobs[0], selected=True)

        self.resetCrackTool()

    def computeMeasure(self):
        """
        It computes the measure between two points. If this point lies inside two blobs
        the distance between the centroids is computed.
        """

        x1 = self.ruler_points[0, 0]
        y1 = self.ruler_points[0, 1]
        x2 = self.ruler_points[1, 0]
        y2 = self.ruler_points[1, 1]

        blob1 = self.annotations.clickedBlob(x1, y1)
        blob2 = self.annotations.clickedBlob(x2, y2)

        if blob1 is not None and blob2 is not None and blob1 != blob2:

            x1 = blob1.centroid[0]
            y1 = blob1.centroid[1]
            x2 = blob2.centroid[0]
            y2 = blob2.centroid[1]

            self.ruler_points[0, 0] = x1
            self.ruler_points[0, 1] = y1
            self.ruler_points[1, 0] = x2
            self.ruler_points[1, 1] = y2

        measurepx = np.sqrt(((x2 - x1) ** 2) + ((y2 - y1) ** 2))

        measure = measurepx * self.map_px_to_mm_factor

        return measure


    def updateRecentFileActions(self):

        settings = QSettings('VCLab', 'TagLab')
        files = settings.value('recentFileList')

        numRecentFiles = min(len(files), self.maxRecentFiles)

        for i in range(numRecentFiles):

            text = "&%d %s" % (i + 1, self.strippedName(files[i]))
            self.recentFileActs[i].setText(text)
            self.recentFileActs[i].setData(files[i])
            self.recentFileActs[i].setVisible(True)

        for j in range(numRecentFiles, self.maxRecentFiles):
            self.recentFileActs[j].setVisible(False)

        self.separatorAct.setVisible((numRecentFiles > 0))

    def strippedName(self, fullFileName):
        return QFileInfo(fullFileName).fileName()

    @pyqtSlot()
    def newProject(self):

        self.resetAll()

        self.setProjectTitle("NONE")

        self.infoWidget.setInfoMessage("TagLab has been reset. To continue open an existing project or load a map.")

    @pyqtSlot()
    def setMapToLoad(self):

        if self.mapWidget is None:

            self.mapWidget = QtMapSettingsWidget(parent=self)
            self.mapWidget.setWindowFlags(Qt.Window)
            self.mapWidget.setWindowModality(Qt.WindowModal)
            self.mapWidget.btnApply.clicked.connect(self.setMapProperties)

            # transfer current data to widget
            self.mapWidget.editMapFile.setText(self.map_image_filename)
            self.mapWidget.editAcquisitionDate.setText(self.map_acquisition_date)
            self.mapWidget.editScaleFactor.setText(str(self.map_px_to_mm_factor))

            self.mapWidget.show()

        else:

            # show it again
            if self.mapWidget.isHidden():
                self.mapWidget.show()


    @pyqtSlot()
    def setMapProperties(self):

        map_filename = self.mapWidget.editMapFile.text()

        # check if the map file exists
        if not os.path.exists(map_filename):

            self.infoWidget.setWarningMessage("Map file does not exist.")

        else:

            # transfer settings
            self.map_image_filename = self.mapWidget.editMapFile.text()
            self.map_acquisition_date = self.mapWidget.editAcquisitionDate.text()
            self.map_px_to_mm_factor = float(self.mapWidget.editScaleFactor.text())

            # close map settings
            self.mapWidget.close()
            self.mapWidget = None

            self.loadMap()

    def loadMap(self):

        QApplication.setOverrideCursor(Qt.WaitCursor)

        # load map and set it
        self.infoWidget.setInfoMessage("Map is loading..")

        self.img_map = QImage(self.map_image_filename)

        if self.img_map.isNull():
            msgBox = QMessageBox()
            msgBox.setText("Could not load or find the image: " + self.map_image_filename)
            msgBox.exec()
            return

        self.img_thumb_map = self.img_map.scaled(self.MAP_VIEWER_SIZE, self.MAP_VIEWER_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.viewerplus.setImage(self.img_map)
        self.mapviewer.setImage(self.img_thumb_map)
        self.viewerplus.viewUpdated.connect(self.updateMapViewer)
        self.mapviewer.setOpacity(0.5)

        QApplication.restoreOverrideCursor()

        self.infoWidget.setInfoMessage("The map has been successfully loading.")

    @pyqtSlot()
    def openProject(self):

        filters = "ANNOTATION PROJECT (*.json)"

        filename, _ = QFileDialog.getOpenFileName(self, "Input Configuration File", self.working_dir, filters)

        if filename:

            self.load(filename)

    @pyqtSlot()
    def openRecentProject(self):
        pass

    @pyqtSlot()
    def saveProject(self):

        filters = "ANNOTATION PROJECT (*.json)"

        filename, _ = QFileDialog.getSaveFileName(self, "Save Configuration File", self.working_dir, filters)

        if filename:

            self.save(filename)

    @pyqtSlot()
    def help(self):
        pass

    @pyqtSlot()
    def about(self):

        lbl1 = QLabel()

        # BIG taglab icon
        pxmap = QPixmap(os.path.join("icons", "taglab100px.png"))
        pxmap = pxmap.scaledToWidth(100)
        lbl1.setPixmap(pxmap)

        lbl2 = QLabel("TagLab was created to support the activity of annotation and extraction of statistical data "
                      "from ortho-maps of benthic communities.\n"
                      "TagLab is an ongoing project of the Visual Computing Lab (http://vcg.isti.cnr.it)")

        lbl2.setWordWrap(True)
        lbl2.setMinimumWidth(330)

        layout = QHBoxLayout()
        layout.addWidget(lbl1)
        layout.addWidget(lbl2)

        widget = QWidget(self)
        widget.setAutoFillBackground(True)
        widget.setStyleSheet("background-color: rgba(60,60,65,100); color: white")
        widget.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        widget.setMinimumWidth(430)
        widget.setMinimumHeight(110)
        widget.setLayout(layout)
        widget.setWindowTitle("About")
        widget.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        widget.show()


    @pyqtSlot()
    def importLabelMap(self):
        """
        Import a label map
        """

        filters = "Image (*.png *.jpg)"
        filename, _ = QFileDialog.getOpenFileName(self, "Input Map File", "", filters)
        created_blobs = self.annotations.import_label_map(filename, self.img_map)
        for blob in created_blobs:
            self.addBlob(blob, selected=False)

    @pyqtSlot()
    def exportData(self):

        exportWidget = QtExportWidget(self.img_map, self.annotations, parent=self)
        exportWidget.setWindowFlags(Qt.Window)
        exportWidget.setWindowModality(Qt.WindowModal)
        exportWidget.show()

    def load(self, filename):
        """
        Load a previously saved projects.
        """

        QApplication.setOverrideCursor(Qt.WaitCursor)

        f = open(filename, "r")

        loaded_dict = json.load(f)

        self.project_name = loaded_dict["Project Name"]
        self.map_image_filename = loaded_dict["Map File"]
        info = QFileInfo(self.map_image_filename)
        if not info.exists():
            self.map_image_filename = QFileInfo(filename).dir().filePath(loaded_dict["Map File"])
            info = QFileInfo(self.map_image_filename)

            if not info.exists():
                (self.map_image_filename, filter) = QFileDialog.getOpenFileName(self, "Couldn't find the map, please select it:", QFileInfo(filename).dir().path(), "Image Files (*.png *.jpg)")

        self.map_acquisition_date = loaded_dict["Acquisition Date"]
        self.map_px_to_mm_factor = float(loaded_dict["Map Scale"])

        for blob_dict in loaded_dict["Segmentation Data"]:

            blob = Blob(None, 0, 0, 0)
            blob.fromDict(blob_dict)
            self.annotations.seg_blobs.append(blob)

        f.close()

        QApplication.restoreOverrideCursor()

        self.loadMap()

        self.setProjectTitle(self.project_name)

        if self.timer is None:
            self.activateAutosave()

        for blob in self.annotations.seg_blobs:
            self.drawBlob(blob)

        self.infoWidget.setInfoMessage("The given project has been successfully open.")

    def save(self, filename):
        """
        Save the current project.
        """

        QApplication.setOverrideCursor(Qt.WaitCursor)



        dict_to_save = {}

        # update project name
        dir = QDir(self.working_dir)
        self.project_name = dir.relativeFilePath(filename)
        self.setProjectTitle(self.project_name)

        dict_to_save["Project Name"] = self.project_name
        dict_to_save["Map File"] = dir.relativeFilePath(self.map_image_filename)
        dict_to_save["Acquisition Date"] = self.map_acquisition_date
        dict_to_save["Map Scale"] = self.map_px_to_mm_factor
        dict_to_save["Segmentation Data"] = [] # a list of blobs, each blob is a dictionary

        for blob in self.annotations.seg_blobs:
            dict = blob.toDict()
            dict_to_save["Segmentation Data"].append(dict)

        str = json.dumps(dict_to_save)

        f = open(filename, "w")
        f.write(str)
        f.close()

        QApplication.restoreOverrideCursor()

        if self.timer is None:
            self.activateAutosave()

        self.infoWidget.setInfoMessage("Current project has been successfully saved.")

    def resetNetworks(self):

        torch.cuda.empty_cache()

        if self.deepextreme_net is not None:
            del self.deepextreme_net
            self.deepextreme_net = None

        if self.corals_classifier is not None:
            del self.corals_classifier
            self.corals_classifier = None


    def applyClassifier(self):

        # free GPU memory
        self.resetNetworks()

        self.tool_used = "AUTOCLASS"

        progress_bar = QtProgressBarCustom(parent=self)
        progress_bar.setWindowFlags(Qt.ToolTip | Qt.CustomizeWindowHint)
        progress_bar.setWindowModality(Qt.NonModal)
        pos = self.viewerplus.pos()
        progress_bar.move(pos.x()+15, pos.y()+30)
        progress_bar.show()

        # setup the desired classifier

        self.infoWidget.setInfoMessage("Setup automatic classification..")

        progress_bar.setMessage("Setup automatic classification..", False)
        QApplication.processEvents()

        self.corals_classifier = MapClassifier("pocillopora")
        self.corals_classifier.updateProgress.connect(progress_bar.setProgress)

        # rescaling the map to fit the target scale of the network

        progress_bar.setMessage("Map rescaling..", False)
        QApplication.processEvents()

        # target scale factor: 1 pixel = 0.9 mm -> 1.1111 pixel / 1mm
        target_scale_factor = 0.9
        scale_factor = target_scale_factor / self.map_px_to_mm_factor

        w = self.img_map.width() * scale_factor
        h = self.img_map.height() * scale_factor

        input_img_map = self.img_map.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

        progress_bar.setMessage("Classification: ", True)
        progress_bar.setProgress(0.0)
        QApplication.processEvents()

        # runs the classifier
        self.infoWidget.setInfoMessage("Automatic classification is running..")
        self.corals_classifier.run(input_img_map, 768, 512, 128)

        if self.corals_classifier.flagStopProcessing is False:

            # import generated label map
            progress_bar.setMessage("Finalizing classification results..", False)
            QApplication.processEvents()

            filename = os.path.join("temp", "labelmap.png")
            created_blobs = self.annotations.import_label_map(filename, self.img_map)
            for blob in created_blobs:
                self.addBlob(blob, selected=False)

        progress_bar.close()
        del progress_bar


    def loadingDeepExtremeNetwork(self):

        # Initialization
        modelName = 'dextr_corals'

        #  Create the network and load the weights
        self.deepextreme_net = resnet.resnet101(1, nInputChannels=4, classifier='psp')

        models_dir = "models/"

        # dictionary layers' names - weights
        state_dict_checkpoint = torch.load(os.path.join(models_dir, modelName + '.pth'),
                                           map_location=lambda storage, loc: storage)

        # Remove the prefix .module from the model when it is trained using DataParallel
        if 'module.' in list(state_dict_checkpoint.keys())[0]:
            new_state_dict = OrderedDict()
            for k, v in state_dict_checkpoint.items():
                name = k[7:]  # remove `module.` from multi-gpu training
                new_state_dict[name] = v
        else:
            new_state_dict = state_dict_checkpoint

        self.deepextreme_net.load_state_dict(new_state_dict)
        self.deepextreme_net.eval()
        if not torch.cuda.is_available():
            print("CUDA NOT AVAILABLE!")

    def segmentWithDeepExtreme(self):

        QApplication.setOverrideCursor(Qt.WaitCursor)

        self.infoWidget.setInfoMessage("Segmentation is ongoing..")

        logfile.info("Segmentation with Deep Extreme begins..")

        pad = 50
        thres = 0.8
        gpu_id = 0
        device = torch.device("cuda:" + str(gpu_id) if torch.cuda.is_available() else "cpu")
        self.deepextreme_net.to(device)

        extreme_points_to_use = self.extreme_points.astype(int)
        pad_extreme = 100
        left_map_pos = extreme_points_to_use[:, 0].min() - pad_extreme
        top_map_pos = extreme_points_to_use[:, 1].min() - pad_extreme

        width_extreme_points = extreme_points_to_use[:, 0].max() - extreme_points_to_use[:, 0].min()
        height_extreme_points = extreme_points_to_use[:, 1].max() - extreme_points_to_use[:, 1].min()
        area_extreme_points = width_extreme_points * height_extreme_points

        (img, extreme_points_new) = utils.prepareForDeepExtreme(self.img_map, extreme_points_to_use, pad_extreme)

        with torch.no_grad():

            extreme_points_ori = extreme_points_new.astype(int)

            #  Crop image to the bounding box from the extreme points and resize
            bbox = helpers.get_bbox(img, points=extreme_points_ori, pad=pad, zero_pad=True)
            crop_image = helpers.crop_from_bbox(img, bbox, zero_pad=True)
            resize_image = helpers.fixed_resize(crop_image, (512, 512)).astype(np.float32)

            #  Generate extreme point heat map normalized to image values
            extreme_points = extreme_points_ori - [np.min(extreme_points_ori[:, 0]),
                                                   np.min(extreme_points_ori[:, 1])] + [pad, pad]

            # remap the input points inside the 512 x 512 cropped box
            extreme_points = (512 * extreme_points * [1 / crop_image.shape[1], 1 / crop_image.shape[0]]).astype(
                np.int)

            # create the heatmap
            extreme_heatmap = helpers.make_gt(resize_image, extreme_points, sigma=10)
            extreme_heatmap = helpers.cstm_normalize(extreme_heatmap, 255)

            #  Concatenate inputs and convert to tensor
            input_dextr = np.concatenate((resize_image, extreme_heatmap[:, :, np.newaxis]), axis=2)
            inputs = torch.from_numpy(input_dextr.transpose((2, 0, 1))[np.newaxis, ...])

            # Run a forward pass
            inputs = inputs.to(device)
            outputs = self.deepextreme_net.forward(inputs)
            outputs = upsample(outputs, size=(512, 512), mode='bilinear', align_corners=True)
            outputs = outputs.to(torch.device('cpu'))

            pred = np.transpose(outputs.data.numpy()[0, ...], (1, 2, 0))
            pred = 1 / (1 + np.exp(-pred))
            pred = np.squeeze(pred)
            result = helpers.crop2fullmask(pred, bbox, im_size=img.shape[:2], zero_pad=True, relax=pad) > thres


            segm_mask = result.astype(int)

            blobs = self.annotations.blobsFromMask(segm_mask, left_map_pos, top_map_pos, area_extreme_points)

            for blob in blobs:
                blob.deep_extreme_points = extreme_points_to_use

            self.resetSelection()
            for blob in blobs:
                self.addBlob(blob, selected=True)
            self.saveUndo()

            logfile.info("Segmentation with Deep Extreme ends.")

            self.infoWidget.setInfoMessage("Segmentation done.")

        QApplication.restoreOverrideCursor()

    def automaticSegmentation(self):

        self.img_overlay = QImage(self.segmentation_map_filename)
        self.viewerplus.setOverlayImage(self.img_overlay)

if __name__ == '__main__':

    # Create the QApplication.
    app = QApplication(sys.argv)

    # set application icon
    app.setWindowIcon(QIcon(os.path.join("icons", "taglab50px.png")))

    slider_style1 = "\
    QSlider::groove::horizontal\
    {\
        border: 1px solid;\
        height: 8px;\
        color: rgb(100,100,100);\
    }"

    slider_style2 = "QSlider::handle::horizontal\
    {\
        background: white;\
        border: 1;\
        width: 18px;\
    }"

    app.setStyleSheet("QLabel {color: white}")
    app.setStyleSheet("QPushButton {background-color: rgb(49,51,53); color: white}")
    app.setStyleSheet(slider_style1)
    app.setStyleSheet(slider_style2)

    app.setStyleSheet("QToolTip {color: white; background-color: rgb(49,51,53); border: none; }")

    # Create the inspection tool
    tool = TagLab()

    # Show the viewer and run the application.
    tool.show()
    sys.exit(app.exec_())
