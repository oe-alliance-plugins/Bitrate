from . import _
from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.Setup import Setup
from Components.ActionMap import ActionMap
from Components.Sources.StaticText import StaticText
from Components.Label import Label
from enigma import ePoint, iPlayableService, eTimer
from Components.config import config, ConfigSubsection, ConfigSelection, ConfigInteger, ConfigYesNo
from Components.ServiceEventTracker import ServiceEventTracker
from Tools.Directories import fileExists
from skin import colors, parseColor
from .bitrate import Bitrate

config.plugins.bitrate = ConfigSubsection()
config.plugins.bitrate.background = ConfigSelection([("#00000000", _("black")), ("#54111112", _("semi-transparent black"))], default="#00000000")
config.plugins.bitrate.x = ConfigInteger(default=300, limits=(0, 1920))
config.plugins.bitrate.y = ConfigInteger(default=300, limits=(0, 1080))
config.plugins.bitrate.force_restart = ConfigYesNo(default=True)
config.plugins.bitrate.show_in_menu = ConfigSelection([("infobar", _("as infobar")), ("extmenu", _("extension menu"))], default="extmenu")
config.plugins.bitrate.infobar_type_services = ConfigSelection([("all", _("all")), ("dvb", _("only DVB"))], default="all")
config.plugins.bitrate.style_skin = ConfigSelection([("compact", _("compact")), ("full", _("full info"))], default="full")
config.plugins.bitrate.z = ConfigSelection([(str(x), str(x)) for x in range(-20, 21)], "1")

infobarModeBitrateInstance = None
bitrateviewer = None


class BitrateViewerExtra(Screen):
	skin_compact = """
		<screen position="200,70" size="300,110" zPosition="%s" backgroundColor="bitrateBackgroundColor" resolution="1920,1080">
			<widget render="Label" source="video_caption" position="10,22" zPosition="1" size="100,32" font="Regular;30" transparent="1"/>
			<widget render="Label" source="audio_caption" position="10,62" zPosition="1" size="100,32" font="Regular;30" transparent="1"/>
			<widget render="Label" source="video" position="105,22" zPosition="1" size="185,32" font="Regular;30" halign="right" transparent="1"/>
			<widget render="Label" source="audio" position="105,62" zPosition="1" size="185,32" font="Regular;30" halign="right" transparent="1"/>
		</screen>""" % (config.plugins.bitrate.z.value)
	skin_info = """
		<screen position="200,300" size="350,160" zPosition="%s" resolution="1920,1080">
			<eLabel position="5,10" size="200,24" text="video kbit/s" font="Regular;20" />
			<eLabel position="5,30" size="80,24" text="min" font="Regular;20" />
			<widget name="vmin" position="5,50" size="80,22" font="Regular;20" />
			<eLabel position="85,30" size="80,24" text="max" font="Regular;20" />
			<widget name="vmax" position="85,50" size="80,22" font="Regular;20" />
			<eLabel position="165,30" size="80,24" text="average" font="Regular;20" />
			<widget name="vavg" position="165,50" size="80,22" font="Regular;20" />
			<eLabel position="245,30" size="80,24" text="current" font="Regular;20" />
			<widget name="vcur" position="245,50" size="80,22" font="Regular;20" />
			<eLabel position="5,80" size="200,24" text="audio kbit/s" font="Regular;20" />
			<eLabel position="5,100" size="80,24" text="min" font="Regular;20" />
			<widget name="amin" position="5,120" size="80,22" font="Regular;20" />
			<eLabel position="85,100" size="80,24" text="max" font="Regular;20" />
			<widget name="amax" position="85,120" size="80,22" font="Regular;20" />
			<eLabel position="165,100" size="80,24" text="average" font="Regular;20" />
			<widget name="aavg" position="165,120" size="80,22" font="Regular;20" />
			<eLabel position="245,100" size="80,24" text="current" font="Regular;20" />
			<widget name="acur" position="245,120" size="80,22" font="Regular;20" />
		</screen>""" % (config.plugins.bitrate.z.value)

	def __init__(self, session, infobar_mode=False):
		self.injectColor("bitrateBackgroundColor", config.plugins.bitrate.background.value)
		if config.plugins.bitrate.style_skin.value == "compact":
			self.skin = self.skin_compact
		else:
				self.skin = self.skin_info
		Screen.__init__(self, session)
		self.infobar_mode = infobar_mode
		self.style_skin = config.plugins.bitrate.style_skin.value
		self.startDelayTimer = eTimer()
		self.startDelayTimer.callback.append(self.bitrateAfrterDelayStart)
		self.title = _("Bitrate viewer")
		if config.plugins.bitrate.style_skin.value == "compact":
			self["video_caption"] = StaticText(_("Video:"))
			self["audio_caption"] = StaticText(_("Audio:"))
			self["video"] = StaticText()
			self["audio"] = StaticText()
			self.skinName = ["BitrateViewerExtraCompact"]
		else:
			self["vmin"] = Label("")
			self["vmax"] = Label("")
			self["vavg"] = Label("")
			self["vcur"] = Label("")
			self["amin"] = Label("")
			self["amax"] = Label("")
			self["aavg"] = Label("")
			self["acur"] = Label("")
			self.skinName = ["BitrateViewerExtra"]
		if not infobar_mode:
			self["actions"] = ActionMap(["WizardActions"],
			{
				x: self.keyCancel for x in ("back", "ok", "right", "left", "down", "up")
			}, -1)
		self.bitrate = Bitrate(session, self.refreshEvent, self.bitrateStopped)
		self.onLayoutFinish.append(self.__layoutFinished)

	def __layoutFinished(self):
		if self.instance:
			self.instance.move(ePoint(config.plugins.bitrate.x.value, config.plugins.bitrate.y.value))
		if not self.infobar_mode:
			self.bitrateUpdateStart()

	def bitrateUpdateStart(self, delay=0):
		self.startDelayTimer.stop()
		self.startDelayTimer.start(delay, True)

	def bitrateAfrterDelayStart(self):
		if not self.bitrateUpdateStatus():
			self.bitrate.start()

	def bitrateUpdateStatus(self):
		return self.bitrate.running

	def bitrateUpdateStop(self):
		self.startDelayTimer.stop()
		if self.bitrateUpdateStatus():
			self.bitrate.stop()
		if self.infobar_mode:
			self.refreshEvent()

	def refreshEvent(self):
		if self.style_skin == "compact":
			self["video"].setText(str(self.bitrate.vcur) + _(" kbit/s"))
			self["audio"].setText(str(self.bitrate.acur) + _(" kbit/s"))
		else:
			self["vmin"].setText(str(self.bitrate.vmin))
			self["vmax"].setText(str(self.bitrate.vmax))
			self["vavg"].setText(str(self.bitrate.vavg))
			self["vcur"].setText(str(self.bitrate.vcur))
			self["amin"].setText(str(self.bitrate.amin))
			self["amax"].setText(str(self.bitrate.amax))
			self["aavg"].setText(str(self.bitrate.aavg))
			self["acur"].setText(str(self.bitrate.acur))

	def keyCancel(self):
		self.bitrate.stop()
		self.close()

	def bitrateStopped(self, retval):
		if not self.infobar_mode:
			self.close()
		else:
			self.refreshEvent()
			if self.shown:
				self.hide()

	@staticmethod
	def injectColor(name, color):
		colors[name] = parseColor(color)


class BitrateViewerSetup(Setup):
	def __init__(self, session):
		Setup.__init__(self, session, setup=None)
		self.title = _("Bitrate viewer setup")

	def createSetup(self):
		indent = "- "
		config_list = [(_("Mode"), config.plugins.bitrate.show_in_menu)]
		if config.plugins.bitrate.show_in_menu.value == "infobar":
			config_list.append((indent + _("Start for type services"), config.plugins.bitrate.infobar_type_services))
			config_list.append((indent + _("Show 'restart bitrate' in extensions menu"), config.plugins.bitrate.force_restart))
		config_list.append((_("Style skin"), config.plugins.bitrate.style_skin))
		if config.plugins.bitrate.style_skin.value == "compact":
			config_list.append((indent + _("Background window") + " *", config.plugins.bitrate.background))
		config_list.append((_("X screen position"), config.plugins.bitrate.x))
		config_list.append((_("Y screen position"), config.plugins.bitrate.y))
		config_list.append((_("Z screen position") + " *", config.plugins.bitrate.z))
		self["config"].list = config_list

	def keySave(self):
		global bitrateviewer
		reset_layout_required = config.plugins.bitrate.style_skin.isChanged() or config.plugins.bitrate.x.isChanged() or config.plugins.bitrate.y.isChanged()
		refresh_required = config.plugins.bitrate.show_in_menu.isChanged() or config.plugins.bitrate.force_restart.isChanged()
		restart_required = self.saveAll()
		if config.plugins.bitrate.show_in_menu.value == "infobar":
			if reset_layout_required and bitrateviewer:
				bitrateviewer.bitrateUpdateStop()
				self.session.deleteDialog(bitrateviewer)
				bitrateviewer = None
			if not bitrateviewer and infobarModeBitrateInstance:
				infobarModeBitrateInstance.resetService()
		elif bitrateviewer:
			bitrateviewer.bitrateUpdateStop()
			self.session.deleteDialog(bitrateviewer)
			bitrateviewer = None
		if refresh_required:
			self.refreshPlugins()
		if fileExists("/usr/lib/enigma2/python/Components/Converter/bitratecalc.so") and self.bitrate.show_in_menu.value == "infobar":
			try:
				from Components.Converter.bitratecalc import eBitrateCalculator  # noqa F401
				self.session.open(MessageBox, _("Using bitrate in the skins with this plugin is not compatible!"), MessageBox.TYPE_WARNING, timeout=5)
			except ImportError:
				pass
		if restart_required:
			self.session.openWithCallback(self.restartConfirm, MessageBox, _("Restart GUI now to apply the changes?"), default=True, type=MessageBox.TYPE_YESNO)
		else:
			self.close()

	@staticmethod
	def refreshPlugins():
		from Components.PluginComponent import plugins
		from Tools.Directories import SCOPE_PLUGINS, resolveFilename
		plugins.clearPluginList()
		plugins.readPluginList(resolveFilename(SCOPE_PLUGINS))


class infobarModeBitrate:
	def __init__(self, session):
		self.session = session
		self.dvb_service = ""
		self.onClose = []
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap={
				iPlayableService.evStart: self.__evStart,
				iPlayableService.evUpdatedInfo: self.__evUpdatedInfo,
				iPlayableService.evEnd: self.__evEnd
			})
		self.InfoBarInstance = None
		self.firstDelayTimer = eTimer()
		self.firstDelayTimer.callback.append(self.infoBarAppendShowHide)
		self.firstDelayTimer.start(5000, True)

	def infoBarAppendShowHide(self):
		from Screens.InfoBar import InfoBar
		self.InfoBarInstance = InfoBar.instance
		if self.InfoBarInstance:
			if hasattr(self.InfoBarInstance, 'onShowHideNotifiers') and self.show_hide_func not in self.InfoBarInstance.onShowHideNotifiers:
				self.InfoBarInstance.onShowHideNotifiers.append(self.show_hide_func)
				self.resetService()

	def show_hide_func(self, func):
		if func:
			self.__onInfoBarBitrateShow()
		else:
			self.__onInfoBarBitrateHide()

	def initDialog(self):
		global bitrateviewer
		if not bitrateviewer and config.plugins.bitrate.show_in_menu.value == "infobar":
			bitrateviewer = self.session.instantiateDialog(BitrateViewerExtra, True)
			self.runBitrateForService()

	def __evStart(self):
		if bitrateviewer:
			if config.plugins.bitrate.infobar_type_services.value == "dvb":
				playref = self.session.nav.getCurrentlyPlayingServiceReference()
				if not playref:
					self.dvb_service = ""
				else:
					str_service = playref.toString()
					if str_service.startswith("1:") and '%3a//' not in str_service:
						self.dvb_service = "dvb"
					else:
						self.dvb_service = "video"
			self.runBitrateForService()

	def runBitrateForService(self):
		if bitrateviewer and config.plugins.bitrate.show_in_menu.value == "infobar" and (config.plugins.bitrate.infobar_type_services.value == "all" or self.dvb_service == "dvb"):
			bitrateviewer.bitrateUpdateStart(500)
			if self.InfoBarInstance and self.InfoBarInstance.shown and not bitrateviewer.shown:
				bitrateviewer.show()

	def __evUpdatedInfo(self):
		self.runBitrateForService()

	def __evEnd(self):
		self.dvb_service = ""
		if bitrateviewer:
			bitrateviewer.bitrateUpdateStop()
			if bitrateviewer.shown:
				bitrateviewer.hide()

	def __onInfoBarBitrateShow(self):
		if bitrateviewer and config.plugins.bitrate.show_in_menu.value == "infobar" and (config.plugins.bitrate.infobar_type_services.value == "all" or self.dvb_service == "dvb"):
			if bitrateviewer.bitrateUpdateStatus() and not bitrateviewer.shown:
				bitrateviewer.show()

	def __onInfoBarBitrateHide(self):
		if bitrateviewer and bitrateviewer.shown:
			bitrateviewer.hide()

	def resetService(self):
		self.initDialog()
		self.__evEnd()
		self.__evStart()


def main(session, **kwargs):
	global bitrateviewer
	if bitrateviewer:
		bitrateviewer.bitrateUpdateStop()
		session.deleteDialog(bitrateviewer)
		bitrateviewer = None
	session.open(BitrateViewerExtra)


def settings(session, **kwargs):
	session.open(BitrateViewerSetup)


def restart(session, **kwargs):
	if session.nav.getCurrentlyPlayingServiceReference() and bitrateviewer and infobarModeBitrateInstance:
		infobarModeBitrateInstance.resetService()


def sessionstart(reason, session, **kwargs):
	global infobarModeBitrateInstance
	if reason == 0 and session and infobarModeBitrateInstance is None:
		infobarModeBitrateInstance = infobarModeBitrate(session)


def Plugins(**kwargs):
	desc = _("Show bitrate for live service")
	list = [PluginDescriptor(name=_("Bitrate setup"), description=desc, where=PluginDescriptor.WHERE_PLUGINMENU, icon="bitrateviewer.png", fnc=settings)]
	list.append(PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart))
	if config.plugins.bitrate.show_in_menu.value == "extmenu":
		list.append(PluginDescriptor(name=_("Bitrate viewer"), description=desc, where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main))
	elif config.plugins.bitrate.force_restart.value:
		list.append(PluginDescriptor(name=_("Restart bitrate viewer"), description=desc, where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=restart))
	return list
