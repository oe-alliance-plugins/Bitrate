from enigma import eConsoleAppContainer, eTimer, iServiceInformation
import six


class Bitrate:
	def __init__(self, session, refresh_func=None, finished_func=None):
		self.session = session
		self.refresh_func = refresh_func
		self.finished_func = finished_func

		self.remainingdata = ""
		self.running = False
		self.clearValues()
		self.datalines = []
		self.container = eConsoleAppContainer()
		self.container.appClosed.append(self.appClosed)
		self.container.dataAvail.append(self.dataAvail)
		self.pollTimer = eTimer()
		self.pollTimer.callback.append(self.pollService)
		self.retryTimer = eTimer()
		self.retryTimer.callback.append(self.start)
		self.retries = 0
		self.polling = False
		self.pollSamples = 0

	def start(self):
		if self.running:
			return
		service = self.session.nav.getCurrentService()
		if not service:
			return
		info = service.info()
		vpid = info.getInfo(iServiceInformation.sVideoPID)
		apid = info.getInfo(iServiceInformation.sAudioPID)
		# sAudioPID prefers the PID cached in the channel list, which is wrong for IPTV entries and
		# after switching tracks; the selected audio track holds the PID that is really decoded
		try:
			audio = service.audioTracks()
			if audio and audio.getNumberOfTracks() > 0:
				cur = audio.getCurrentTrack()
				if cur >= 0:
					track_pid = audio.getTrackInfo(cur).getPID()
					if track_pid and track_pid > 0:
						apid = track_pid
		except Exception:
			pass
		# live DVB: ask the service which demux it really uses, guessing demux0 reads
		# nothing as soon as the service lives on another demux (PiP, recording, ...)
		demux = None
		try:
			demux = info.getInfoString(iServiceInformation.sLiveStreamDemuxId)
		except Exception:
			pass
		demux = int(demux) if demux else None
		adapter = 0
		try:
			stream = service.stream()
			if stream:
				streamdata = stream.getStreamingData()
				if streamdata:
					if 'demux' in streamdata:
						demux = streamdata["demux"]
					if 'adapter' in streamdata:
						adapter = streamdata["adapter"]
		except Exception:
			pass
		if demux is None and hasattr(iServiceInformation, "sVideoBitrate"):
			# no demux: servicemp3 (and friends) measure the bitrate themselves
			self.running = True
			self.polling = True
			self.pollSamples = 0
			self.clearValues()
			self.vmin = self.amin = 50000
			self.pollTimer.start(1000, False)
			return
		if demux is None:
			demux = 0
		if (vpid is None or vpid < 0) and (apid is None or apid < 0):
			# PMT not parsed yet (called right after zapping) - try again shortly
			if self.retries < 20:
				self.retries += 1
				self.retryTimer.start(500, True)
			return
		self.retries = 0
		cmd = "bitrate %d %d %d %d" % (adapter, demux, vpid, apid)
		self.running = True
		self.container.execute(cmd)

	def pollService(self):
		service = self.session.nav.getCurrentService()
		if not service:
			return
		info = service.info()
		v = info.getInfo(iServiceInformation.sVideoBitrate)
		a = info.getInfo(iServiceInformation.sAudioBitrate)
		if v < 0 and a < 0:
			return
		self.pollSamples += 1
		if self.pollSamples < 2:  # first sample only sets the baseline
			return
		v = max(v, 0)
		a = max(a, 0)
		n = self.pollSamples - 1
		self.vcur, self.acur = v, a
		# 0 is just start-up / an idle second, it must not become the minimum
		if v > 0:
			self.vmin = min(self.vmin, v) or v
		if a > 0:
			self.amin = min(self.amin, a) or a
		self.vmax, self.amax = max(self.vmax, v), max(self.amax, a)
		if self.vmin == 50000:
			self.vmin = 0
		if self.amin == 50000:
			self.amin = 0
		self.vavg = (self.vavg * (n - 1) + v) // n
		self.aavg = (self.aavg * (n - 1) + a) // n
		if self.refresh_func:
			self.refresh_func()

	def clearValues(self):
		self.vmin = 0
		self.vmax = 0
		self.vavg = 0
		self.vcur = 0
		self.amin = 0
		self.amax = 0
		self.aavg = 0
		self.acur = 0

	def stop(self):
		self.pollTimer.stop()
		self.retryTimer.stop()
		self.retries = 0
		self.polling = False
		self.container.kill()
		self.remainingdata = ""
		self.clearValues()
		self.running = False

	def appClosed(self, retval):
		self.pollTimer.stop()
		self.remainingdata = ""
		self.clearValues()
		self.running = False
		if self.finished_func:
			self.finished_func(retval)

	def dataAvail(self, str):
		#prepend any remaining data from the previous call
		str = self.remainingdata + six.ensure_str(str)
		#split in lines
		newlines = str.split('\n')
		#'str' should end with '\n', so when splitting, the last line should be empty. If this is not the case, we received an incomplete line
		if len(newlines[-1]):
			#remember this data for next time
			self.remainingdata = newlines[-1]
			newlines = newlines[0:-1]
		else:
			self.remainingdata = ""

		for line in newlines:
			if len(line):
				self.datalines.append(line)
		if len(self.datalines) >= 2:
			try:
				self.vmin, self.vmax, self.vavg, self.vcur = self.datalines[0].split(' ')
				self.amin, self.amax, self.aavg, self.acur = self.datalines[1].split(' ')
			except Exception:
				self.clearValues()
			self.datalines = []
			if self.refresh_func:
				self.refresh_func()
