#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <errno.h>
#include <unistd.h>
#include <sys/select.h>
#include <sys/time.h>
#include <linux/dvb/dmx.h>

#include <iostream>
#include <vector>
#include <deque>

/* #define USE_TS_FILTER */

#ifdef USE_TS_FILTER
# define TS_LEN       188
# define TS_SYNC_BYTE 0x47
# define BUFFER_SIZE  (TS_LEN * 2048)
#else
# define BUFFER_SIZE (256 * 1024)
#endif

#ifdef USE_TS_FILTER
int syncTS(unsigned char *buf, int len)
{
	int i = 0;
	for (i = 0; i < len; i++)
	{
		if (buf[i] == TS_SYNC_BYTE)
		{
			if ((i + TS_LEN) < len)
			{
				if (buf[i + TS_LEN] != TS_SYNC_BYTE) continue;
			}
			break;
		}
	}
	return i;
}
#endif

unsigned long timevalToMs(const struct timeval *tv)
{
	return(tv->tv_sec * 1000) + ((tv->tv_usec + 500) / 1000);
}

long deltaTimeMs(struct timeval *tv, struct timeval *last_tv)
{
	return timevalToMs(tv) - timevalToMs(last_tv);
}

int Select(int maxfd, fd_set *readfds, fd_set *writefds, fd_set *exceptfds, struct timeval *timeout)
{
	int retval;
	fd_set rset, wset, xset;
	timeval interval;
	timerclear(&interval);

	/* make a backup of all fd_set's and timeval struct */
	if (readfds) rset = *readfds;
	if (writefds) wset = *writefds;
	if (exceptfds) xset = *exceptfds;
	if (timeout) interval = *timeout;

	while (1)
	{
		retval = select(maxfd, readfds, writefds, exceptfds, timeout);

		if (retval < 0)
		{
			/* restore the backup before we continue */
			if (readfds) *readfds = rset;
			if (writefds) *writefds = wset;
			if (exceptfds) *exceptfds = xset;
			if (timeout) *timeout = interval;
			if (errno == EINTR) continue;
			std::cout << "select failed " << errno << std::endl;
			break;
		}

		break;
	}
	return retval;
}

ssize_t Read(int fd, void *buf, size_t count)
{
	int retval;
	char *ptr = (char*)buf;
	size_t handledcount = 0;
	while (handledcount < count)
	{
		retval = read(fd, &ptr[handledcount], count - handledcount);

		if (retval == 0) return handledcount;
		if (retval < 0)
		{
			if (errno == EINTR) continue;
			std::cout << "read failed " << errno << std::endl;
			return retval;
		}
		handledcount += retval;
	}
	return handledcount;
}

ssize_t NBRead(int fd, void *buf, size_t count)
{
	int retval;
	while (1)
	{
		retval = ::read(fd, buf, count);
		if (retval < 0)
		{
			if (errno == EINTR) continue;
			std::cout << "read failed " << errno << std::endl;
		}
		return retval;
	}
}

/* Open a demux filter for one PID. ts == false: PES payload tap; ts == true: raw TS packets of the
 * PID, the way the recorder opens them. Some drivers (gbquad4kpro, 4K HEVC) deliver nothing to a
 * PES tap on a PID that the video decoder is using, but do deliver it as a TS tap. */
static int openFilter(const char *filename, int pid, bool ts)
{
	if (pid < 0 || pid > 0x1fff)
		return -1;
	int fd = ::open(filename, O_RDONLY);
	if (fd < 0)
		return -1;
	::fcntl(fd, F_SETFL, O_NONBLOCK);
	::ioctl(fd, DMX_SET_BUFFER_SIZE, 8 * 1024 * 1024);
	dmx_pes_filter_params flt;
	memset(&flt, 0, sizeof(flt));
	flt.pes_type = DMX_PES_OTHER;
	flt.pid = pid;
	flt.input = DMX_IN_FRONTEND;
	flt.output = ts ? DMX_OUT_TSDEMUX_TAP : DMX_OUT_TAP;
	flt.flags = ts ? 0 : DMX_IMMEDIATE_START;
	if (::ioctl(fd, DMX_SET_PES_FILTER, &flt) < 0 || (ts && ::ioctl(fd, DMX_START) < 0))
	{
		::close(fd);
		return -1;
	}
	return fd;
}

void measureBitrate(int adapter, int demux, bool oneshot, std::vector<int> pids)
{
	char filename[128];
	snprintf(filename, 128, "/dev/dvb/adapter%d/demux%d", adapter, demux);
	std::vector<int> fds;
	std::vector<bool> is_ts;
	/* (bytes, ms) of the last few reporting intervals: soft-descrambled / bursty PIDs deliver
	 * nothing for a whole second now and then, so 'current' is averaged over a short window */
	std::vector<std::deque<std::pair<unsigned long long, int> > > hist;
	std::vector<unsigned long long> last_nonzero;
	std::vector<int> zero_run;
	std::vector<unsigned long long> b_total, b_tot1, min_kb_s, max_kb_s, avg_kb_s, curr_kb_s;
	for (unsigned int i = 0; i < pids.size(); i++)
	{
		int fd = openFilter(filename, pids[i], false);
		fds.push_back(fd);
		is_ts.push_back(false);
		hist.push_back(std::deque<std::pair<unsigned long long, int> >());
		last_nonzero.push_back(0);
		zero_run.push_back(0);

		b_total.push_back(0);
		b_tot1.push_back(0);
		min_kb_s.push_back(50000ULL);
		max_kb_s.push_back(0);
		curr_kb_s.push_back(0);
		avg_kb_s.push_back(0);
	}

	struct timeval first_tv, last_print_tv;

	gettimeofday(&first_tv, 0);
	last_print_tv.tv_sec = first_tv.tv_sec;
	last_print_tv.tv_usec = first_tv.tv_usec;

	while (1)
	{
		unsigned char buf[BUFFER_SIZE];
		int maxfd = 0;
		fd_set rset;
		FD_ZERO(&rset);
		struct timeval timeout;
		timeout.tv_sec = 1;
		timeout.tv_usec = 0;
		for (unsigned int i = 0; i < fds.size(); i++)
		{
			if (fds[i] >= 0) FD_SET(fds[i], &rset);
			if (fds[i] >= maxfd) maxfd = fds[i] + 1;
		}

		int result = Select(maxfd, &rset, NULL, NULL, &timeout);
		/* result == 0 only means that no data arrived within the timeout (e.g. a PID that is
		 * idle for a moment or a slow demux start); keep going and report 0 kbit/s instead of exiting */
		if (result < 0) break;

		for (unsigned int i = 0; i < fds.size(); i++)
		{
			if (fds[i] >= 0 && FD_ISSET(fds[i], &rset))
			{
				int b_len = 0;
				/* drain the filter; an EOVERFLOW read just means data was dropped, keep counting */
				for (int n = 0; n < 64; n++)
				{
					int r = ::read(fds[i], buf, sizeof(buf));
					if (r > 0)
					{
						b_total[i] += r;
						b_tot1[i] += r;
						continue;
					}
					if (r < 0 && (errno == EINTR || errno == EOVERFLOW)) continue;
					break;
				}
				int b_start = 0;
#ifdef USE_TS_FILTER
				if (b_len >= TS_LEN)
				{
					b_start = syncTS(buf, b_len);
				}
				else
				{
					b_len = 0;
				}
#endif
				int b = b_len - b_start;
				if (b <= 0) continue;
				b_total[i] += b;
				b_tot1[i] += b;
			}
		}
		struct timeval tv;
		gettimeofday(&tv, 0);
		int d_print_ms = deltaTimeMs(&tv, &last_print_tv);
		if (d_print_ms >= 1000)
		{
			for (unsigned int i = 0; i < fds.size(); i++)
			{
				int d_tim_ms = deltaTimeMs(&tv, &first_tv);
				if (d_tim_ms <= 0) d_tim_ms = 1;
				/* a PES tap that never delivered a byte: retry as TS tap */
				if (!is_ts[i] && fds[i] >= 0 && b_total[i] == 0 && d_tim_ms >= 2000)
				{
					::close(fds[i]);
					fds[i] = openFilter(filename, pids[i], true);
					is_ts[i] = true;
				}
				avg_kb_s[i] = (b_total[i] * 8ULL) / (unsigned long long)d_tim_ms;
				hist[i].push_back(std::make_pair(b_tot1[i], d_print_ms));
				if (hist[i].size() > 5) hist[i].pop_front();
				unsigned long long w_bytes = 0, w_ms = 0;
				for (unsigned int h = 0; h < hist[i].size(); h++)
				{
					w_bytes += hist[i][h].first;
					w_ms += hist[i][h].second;
				}
				curr_kb_s[i] = w_ms ? (w_bytes * 8ULL) / w_ms : 0;
				/* soft-descrambled PIDs can stay silent for several seconds: hold the last value
				 * for a while before admitting that nothing arrives */
				if (curr_kb_s[i] > 0)
				{
					last_nonzero[i] = curr_kb_s[i];
					zero_run[i] = 0;
				}
				else if (last_nonzero[i] > 0 && ++zero_run[i] <= 6)
					curr_kb_s[i] = last_nonzero[i];
#ifdef USE_TS_FILTER
				/* compensate for TS and PES overhead */
				avg_kb_s[i] = avg_kb_s[i] * 97ULL / 100ULL;
				curr_kb_s[i] = curr_kb_s[i] * 97ULL / 100ULL;
#else
				if (is_ts[i])
				{
					/* compensate for TS header overhead */
					avg_kb_s[i] = avg_kb_s[i] * 97ULL / 100ULL;
					curr_kb_s[i] = curr_kb_s[i] * 97ULL / 100ULL;
				}
				else
				{
					/* compensate for PES overhead */
					avg_kb_s[i] = avg_kb_s[i] * 99ULL / 100ULL;
					curr_kb_s[i] = curr_kb_s[i] * 99ULL / 100ULL;
				}
#endif
				b_tot1[i] = 0;

				/* ignore the start-up seconds (and PIDs that are idle) for the minimum */
				if (curr_kb_s[i] > 0 && curr_kb_s[i] < min_kb_s[i])
				{
					min_kb_s[i] = curr_kb_s[i];
				}
				if (curr_kb_s[i] > max_kb_s[i])
				{
					max_kb_s[i] = curr_kb_s[i];
				}
				last_print_tv.tv_sec = tv.tv_sec;
				last_print_tv.tv_usec = tv.tv_usec;
				if (oneshot)
				{
					std::cout << curr_kb_s[i] << std::endl;
				}
				else
				{
					std::cout << (min_kb_s[i] == 50000ULL ? 0ULL : min_kb_s[i]) << " " << max_kb_s[i] << " " << avg_kb_s[i] << " " << curr_kb_s[i] << std::endl;
				}
			}
			if (oneshot) break;
		}
	}
}

int main(int argc, char *argv[])
{
	if (argc < 4)
	{
		fprintf(stderr, "usage: %s <adapterid> <demuxid> <pid> [..<pidN>]\n", argv[0]);
		exit(-1);
	}
	std::vector<int> pids;
	for (int i = 2; i < argc - 1; i++)
	{
		pids.push_back(atoi(argv[i + 1]));
	}
	measureBitrate(atoi(argv[1]), atoi(argv[2]), false, pids);
	return 0;
}
