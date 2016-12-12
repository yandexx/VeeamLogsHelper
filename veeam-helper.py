import sublime, sublime_plugin
import re, glob, os, time, threading

class agent_start:
    def __init__(self):
        self.date = ''
        self.thread = 0
        self.host = ''
        self.logName = ''
        self.agent_id = '00000000-0000-0000-000000000000'
        self.is_cloud = False
    def __repr__(self):
        return self.date + ' <' + self.thread + '>, id ' + self.agent_id + ' '+ self.host + ', ' + self.logName

class agent_session:
    def __init__(self):
        self.date = ''
        self.thread = 0
        self.id = ''
        self.agent_id = ''
        self.host = ''
    def __repr__(self):
        return self.date + ' <' + self.thread + '> '+ self.id + ', ' + self.host

agent_starts   = []
agent_sessions = []
veeam_ips = set()
veeam_hostname = set()
loaded = False

def collect_info(path):
    print("Collecting...")
    agent_starts.clear()
    agent_sessions.clear()

    folder = os.path.dirname(path)
    # Take all .log files except for Agent ones
    job_files = list(set(glob.glob(os.path.join(folder, "*.log"))) - set(glob.glob(os.path.join(folder, "Agent*.log"))))
    if job_files == []:
        return
    
    # [31.08.2016 01:43:18] <44> Info     [AgentMngr] Starting agent with normal priority, Host 'host.vmware.local', logName: 'Job_Name/Agent.Job_Name.Source.etc.Disks.log'. IPs: '10.40.106.110', is x64 agent preferred: 'True'.
    agent_start_regex   = re.compile("\[(.+?)\] <(\d+?)> .+? Starting agent with .+?, Host '(.+?)', logName: '(.+?)'")
    # [AgentMngr] Agent has been started, ID 'c04380c1-ead0-4e85-9a65-3953ce522985'
    agent_started_regex = re.compile("<(\d+?)> .+? \[AgentMngr\] Agent has been started, ID '(.{36})'")
    # [ProxyAgent] Starting CProxyAgent. Agent id 8f117263-9110-4411-b13d-44d4ea452f90
    starting_cproxy_agent_regex = re.compile("<(\d+?)> .+? \[ProxyAgent\] Starting CProxyAgent\. Agent id (.{36})")
    # [31.08.2016 01:43:18] <44> Info     [ProxyAgent] Starting client agent session, id '72f94b78-1b0a-4e24-a42c-298f838ae9d9', host 'host.vmware.local', agent id '4ee56990-e963-4c05-a2bf-5a7670063f38', IPs '10.40.111.110:2500', PID '6160'
    agent_session_regex = re.compile("\[(.+?)\] <(\d+?)> .+? Starting client agent session, id '(.{36})', host '(.+?)', agent id '(.{36})'")
    veeam_ips_regex     = re.compile("\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
    machine_name_regex  = re.compile("MachineName: \[(.+?)\]")
    # [31.08.2016 01:43:18] ... AsyncInvokerState Progress: 0 State: Complete Result: <SIResponse CIResult="&lt;CloudHostAgentSpec&gt;&lt;Id&gt;b565ea73-28b0-4ef6-bbb1-25e096e2d47f&lt;/Id&gt;&lt;Addrs&gt;&lt;string&gt;&lt;Root Ip=&quot;172.18.5.3&quot; Port=&quot;6180&quot; /&gt;&lt;/string&gt;&lt;/Addrs&gt;&lt;GateConnectionId&gt;9774014b-cc5c-453d-b076-4f0d13698388&lt;/GateConnectionId&gt;&lt;ChannelCryptoKeySet&gt;&lt;SerializedKeySet&gt;&lt;Raw&gt;&lt;/Raw&gt;&lt;/SerializedKeySet&gt;&lt;/ChannelCryptoKeySet&gt;&lt;/CloudHostAgentSpec&gt;" />
    cloud_agent_started_regex = re.compile("\[(.+?)\] <(\d+?)> .+? AsyncInvokerState Progress:.+? State: Complete Result: <SIResponse CIResult=\"(.+?)\" />")
    cloud_agent_started_regex_ip = re.compile("Root Ip=&quot;(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})&quot;")

    for job_file in job_files:
        with open(job_file) as f:
            #print (job_file)
            for line in f:
                if "Starting agent with" in line:
                    match = agent_start_regex.search(line)
                    if match:
                        ags = agent_start()  
                        ags.date = match.group(1)
                        ags.thread = match.group(2)
                        ags.host = match.group(3)
                        ags.logName = match.group(4)
                        agent_starts.append(ags)
                elif "Agent has been started" in line or "Starting CProxyAgent" in line:
                    match  = agent_started_regex.search(line)
                    match2 = starting_cproxy_agent_regex.search(line)
                    if match:
                        if agent_starts:
                            for a in reversed(agent_starts):
                                if a.thread == match.group(1):
                                    a.agent_id = match.group(2)
                                    break
                    if match2:
                        if agent_starts:
                            for a in reversed(agent_starts):
                                if a.thread == match2.group(1):
                                    a.agent_id = match2.group(2)
                                    break
                elif "Starting client agent session" in line:
                    match = agent_session_regex.search(line)
                    if match:
                        ags = agent_session()
                        ags.date = match.group(1)
                        ags.thread = match.group(2)
                        ags.id = match.group(3)
                        ags.host = match.group(4)
                        ags.agent_id = match.group(5)
                        agent_sessions.append(ags)
                elif "Unicast IPAddresses" in line:
                    for ip in veeam_ips_regex.findall(line):
                        veeam_ips.add(ip)
                elif "MachineName:" in line:
                    match = machine_name_regex.search(line)
                    if match:
                        veeam_hostname.add(match.group(1).lower())
                elif "AsyncInvokerState Progress" in line:
                    match = cloud_agent_started_regex.search(line)
                    if match:
                        match_ip = cloud_agent_started_regex_ip.search(match.group(3))
                        if match_ip:
                            ags = agent_start()
                            ags.date = match.group(1)
                            ags.thread = match.group(2)
                            ags.host = match_ip.group(1)
                            ags.is_cloud = True
                            agent_starts.append(ags)

def lookup_agent (digest, datetime):
    # find the correct session
    session_matched = []
    #print ("agent_sessions",agent_sessions)
    for ags in agent_sessions:
        if ags.id.startswith(digest):
            session_matched.append(ags)
    if not session_matched:
        print("No sessions")
        return
    if len(session_matched) > 1:
        session_matched.sort(key=sort_by_date)

        ss = None
        for s in session_matched:
            if sortable_date(s.date) <= sortable_date(datetime):
                ss = s
            else:
                break

        if ss == None:
            print("No suitable sessions by date")
            return
        session_matched = ss
    else:
        session_matched = session_matched[0]
    
    thread = session_matched.thread
    agent_id = session_matched.agent_id
    
    print("digest", digest, "at", session_matched)

    # lookup by agent id
    for a in agent_starts:
        if agent_id == a.agent_id:
            return a

def sort_by_date (date):
    # "31.08.2016 01:43:18" => "2016.08.31 01:43:18"
    date_key = date.date[6:10] + date.date[3:5] + date.date[0:2] + date.date[12:20]
    return date_key

def sortable_date (date):
    # "31.08.2016 01:43:18" => "2016.08.31 01:43:18"
    date_key = date[6:10] + date[3:5] + date[0:2] + date[12:20]
    return date_key

class AgentLookup(sublime_plugin.EventListener):
    def __init__(self):
        self.loaded = False

    def on_load(self, view):
        return
        #if os.path.splitext(view.file_name())[1] != '.log':
        #    return
        #self.collect(view)

    def collect(self, view):
        #if not self.loaded:
        collect_info(view.file_name())
        #    self.loaded = True
        
        # for p in agent_starts:
        #     print (p)

    def agent_is_veeam(self, agent):
        if agent.host in veeam_ips or agent.host.split('.', maxsplit=1)[0] in veeam_hostname:
            return True
        else:
            return False

    def on_hover(self, view, point, hover_zone):
        if view.file_name() == None:
            return
        if os.path.splitext(view.file_name())[1] != '.log':
            return

        row, col = view.rowcol(point)
        
        # locate agent digest "(0abc)" in the vicinity
        line_beginning = view.text_point(row, 0)
        digest_region = view.find("\([0-9abcdef]{4}\)", line_beginning)
        if digest_region.empty():
            return
        if not digest_region.contains(point):
            return

        digest = view.substr(digest_region)[1:5]

        print (digest)

        current_line = view.substr(view.line(point))
        
        p = re.compile("^\[(.+?)\]")
        m = p.search(current_line)
        if m: 
            datetime = m.group(1)

        agent = None
        if view.file_name():
            self.collect(view)
            agent = lookup_agent(digest, datetime)
        else:
            return

        # render the tooltip
        if agent:
            agent_log_exists = False
            if self.agent_is_veeam(agent):
                # Look for the agent in the same folder as the Job/Task log
                agent_abs_path = os.path.join(os.path.dirname(view.file_name()), os.path.basename(agent.logName))
            else:
                # Go find it in the proxy/repository folder
                logs_root = os.path.abspath(os.path.join(os.path.dirname(view.file_name()), os.pardir + os.sep + os.pardir + os.sep + os.pardir))
                agent_abs_path = os.path.join(logs_root, agent.host, 'Backup', agent.logName)
            if os.path.exists(agent_abs_path):
                agent_log_exists = True

            if self.agent_is_veeam(agent):
                is_veeam = " <em>(Veeam server)</em>"
            else:
                is_veeam = " "

            if agent_log_exists:
                log_string = "<strong>Log</strong>: <a href=\"" + agent_abs_path + "\">" + agent.logName + "</a><br>"
            else:
                log_string = "<strong>Log</strong>: " + agent.logName + " <em>(not found)</em><br>"

            def on_link_navigate(href):
                view.window().run_command("veeam_open_file", {'path': agent_abs_path, 'datetime': datetime})

            if agent.is_cloud:
                host = 'Cloud host (gateway ' + agent.host + ')'
            else:
                host = agent.host

            popup_body = "<body>" + \
            "<style>body {font-family: sans-serif;}</style>"+ \
            "<strong>Host</strong>: " + host + is_veeam + "<br>" + \
            log_string + \
            "<strong>Started</strong>: " + agent.date + \
            "</body>"
            view.show_popup(popup_body, location=point, flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY, max_width=1200, on_navigate=on_link_navigate)

class VeeamOpenFileCommand(sublime_plugin.WindowCommand):
    def run(self, path, datetime=None):
        v = self.window.open_file(path)
        w = AsyncOpenLog(v, datetime)
        w.start()

class AsyncOpenLog(threading.Thread):
    def __init__(self, view, datetime):
        threading.Thread.__init__(self)
        self.view = view
        self.datetime = datetime

    def run(self):
        while self.view.is_loading() == True:
           time.sleep(0.1)

        # find 09.10.2016 22:36:36
        print(self.datetime)
        location = self.view.find(self.datetime, 0, sublime.LITERAL)
        print (location)
        if location.empty():
            # find 09.10.2016 22:36:3
            location = self.view.find(self.datetime[0:-1], 0, sublime.LITERAL)
            if location.empty():
                # find 09.10.2016 22:36
                location = self.view.find(self.datetime[0:-3], 0, sublime.LITERAL)
                if location.empty():
                    # find 09.10.2016 22:3
                    location = self.view.find(self.datetime[0:-4], 0, sublime.LITERAL)
                    if location.empty():
                        # find 09.10.2016 22
                        location = self.view.find(self.datetime[0:-6], 0, sublime.LITERAL)
                        if location.empty():
                            # find 09.10.2016 or give up
                            location = self.view.find(self.datetime[0:-9], 0, sublime.LITERAL)
        if location:
            self.view.show_at_center(location)
