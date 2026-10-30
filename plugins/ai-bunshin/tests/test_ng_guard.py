"""NG の見張り（ng_guard.py）のテスト。止めるべきもの（bad）と、止めてはいけない日常の作業（good）。
正規表現を変えたら必ず実行する：python3 tests/test_ng_guard.py（失敗があれば終了コード1）"""
import json,subprocess,sys,os,tempfile
G=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","scripts","ng_guard.py")
R=tempfile.mkdtemp(prefix="ngtest_")
# R は「本人のフォルダ」：印（設定/config.json・00_タスク管理/data/tasks.json のどれか）がある（見張りはここでだけ動く）
os.makedirs(os.path.join(R,"設定")); os.makedirs(os.path.join(R,"00_タスク管理","data"))
open(os.path.join(R,"設定","config.json"),"w").write("{}"); open(os.path.join(R,"00_タスク管理","data","tasks.json"),"w").write("{}")
def run(tool,inp):
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":tool,"tool_input":inp}),capture_output=True,text=True,cwd=R,env={**os.environ,"CLAUDE_PROJECT_DIR":R})
    return "STOP" if "deny" in p.stdout else "pass"
bad=[
"rm x","/bin/rm x","\\rm x","command rm x","env rm x","find 02_成果物 -type f -exec /bin/rm {} +","find . -exec rm {} \;","find . -name x -delete",
"perl -e 'unlink \"x\"'","python3 <<EOF\nimport shutil;shutil.rmtree('a')\nEOF","python3 -c \"import shutil;shutil.rmtree('a')\"","truncate -s 0 02_成果物/a.md",
"> 03_インプット/x","echo hi > 03_インプット/x","mv x ~/.Trash/","mv 02_成果物/a ~/.Trash/a","git checkout .","git checkout -- .","git restore .","git stash drop",
"/usr/bin/curl http://x","wget http://x","open mailto:a@b.c","open https://example.com","ruby -e 'File.delete(\"x\")'","node -e \"require('fs').rmSync('x')\"",
"bash -c 'rm x'","sh -c \"rm -rf x\"","echo x | xargs -I{} rm {}","xargs rm < list","/usr/bin/sudo ls","sudo ls","/bin/launchctl list","launchctl load x","kill -9 1","/bin/kill 1",
"cat x | sh","eval \"rm x\"","$(echo rm) x","r\\m x","dd if=/dev/null of=02_成果物/a.md","cp /dev/null 02_成果物/a.md",": > 02_成果物/a.md","tee 03_インプット/x < a","git push","gh pr create","/usr/bin/git push","git -C . push","git -c x=y push","git clean -fd","pip install x","python3 -m pip install x","brew install x","npm i x","osascript -e 'x'","/usr/bin/osascript x","ssh h","nc h 1","python3 -c 'import os;os.system(\"rm x\")'","python3 -c 'import os;os.system(\"curl x\")'","mv 02_成果物/a /dev/null","rm\tx","rm\\\nx","echo x >| 03_インプット/y","sed -i '' s/a/b/ 03_インプット/x","sed -i '' s/a/b/ ./CLAUDE.md","ln -sf /dev/null 02_成果物/a","cat a > .claude/settings.json","echo {} > .claude/settings.local.json","chmod 777 x","open -a Mail","shortcuts run x","mail -s hi a@b","swaks x","python3 -c \"import smtplib\"","zsh -c 'rm x'","bash -lc 'rm x'","sh -c 'ls; rm x'","git reset --hard","git branch -D x","git rebase -i","mkdir x && rm -r x","true || rm x","if true; then rm x; fi","{ rm x; }","for f in *; do rm $f; done","find . -delete","rsync -a a b","find . -name x -execdir rm {} +","find . -ok rm {} \;",
]
good=[
"grep -rn rm .","ls -la","cat 02_成果物/a.md","python3 /x/update_dashboard.py --plan-context","python3 /x/update_dashboard.py","mv 02_成果物/a 02_成果物/b","sed -i '' s/a/b/ 02_成果物/a.md","sed -i s/a/b/ 02_成果物/a.md","echo \"kill\"","echo rm","git status","git diff","git log --oneline","grep -n curl README.md","cat 04_ナレッジ/判断基準.md","head -5 x","python3 -c \"print(1)\"","python3 -m json.tool x","mkdir -p 02_成果物/総務","cp 02_成果物/a 02_成果物/b","ls 03_インプット/","cat 03_インプット/x.csv","python3 - <<EOF\nimport json;print(json.load(open('00_タスク管理/data/tasks.json')))\nEOF","wc -l x","date","echo 'please do not rm files' > 02_成果物/note.md","grep -rn 'git push' 04_ナレッジ","rg 'shutil.rmtree' .","python3 -c \"import openpyxl\"","command -v claude","uname","echo \"normal: 3+4\"","git add -A","git commit -m x","grep -n \"su\" x","ls | grep -i time","cat a | sort","python3 script.py --arg", "cd 02_成果物 && ls","echo $(date)","python3 -c \"from urllib.parse import quote\"","python3 -c \"import subprocess;print(1)\"","python3 -c \"import socket\"","echo 'import requests.post' > a.txt","python3 build.py  # fix rmdir","grep rm foo","cat x; rm_helper_notes","ls rm-notes","echo done;kill-switch","mv 02_成果物/a.xlsx 02_成果物/共通/","git restore-notes","git checkout main","git checkout -b x","git branch","sed -i '' s/a/b/ 02_成果物/CLAUDE.md.bak","echo hello > 02_成果物/a.md","python3 x.py > 02_成果物/out.txt","pip list","pip3 --version","npm ls","git push-notes","gh --version","wget-notes","time ls","nice ls","echo \"a; b\"","grep 'a|b' x","awk '{print $1}' x","ls ~/Library","open 02_成果物/a.xlsx","open -R 02_成果物/a.xlsx","touch 02_成果物/a",
]
fail=0
print("## BAD")
for c in bad:
    r=run("Bash",{"command":c})
    if r!="STOP": fail+=1; print("MISS",repr(c))
print("## GOOD")
for c in good:
    r=run("Bash",{"command":c})
    if r!="pass": fail+=1; print("FALSEPOS",repr(c))
print("## PATHS")
for t,p in [("Write",R+"/03_インプット/x.csv"),("Write",R+"/.claude/settings.json"),("Edit",R+"/.claude/settings.local.json"),("Write",R+"/.claude/rules/ai-bunshin-common.md"),("Write",R+"/02_成果物/a.md"),("Write",R+"/CLAUDE.md"),("Write",R+"/設定/config.json"),("Write",R+"/03_インプット/../.claude/settings.json"),("MultiEdit",R+"/03_インプット/a"),("NotebookEdit",R+"/03_インプット/a.ipynb"),("Write",R+"/.claude/hooks/x.sh"),("Write",R+"/.claude/settings.JSON")]:
    k="file_path" if t!="NotebookEdit" else "notebook_path"
    want="pass" if ("02_成果物" in p or p.endswith("CLAUDE.md") or "設定/config" in p) else "STOP"
    r=run(t,{k:p})
    if r!=want: fail+=1; print("PATH", r, "want", want, t, p.replace(R,"<R>"))
# 開発の置き場所（config の dev.projects と 05_開発/）の中だけ、その案件へのインストールを通す
EXT=tempfile.mkdtemp(prefix="ngrepo_")
os.makedirs(os.path.join(R,"設定"),exist_ok=True); os.makedirs(os.path.join(R,"05_開発","tool"),exist_ok=True)
json.dump({"dev":{"default_mode":"local","projects":[{"name":"ext","mode":"git","path":EXT}]}},open(os.path.join(R,"設定","config.json"),"w"))
dev_good=["cd 05_開発/tool && npm install","cd 05_開発/tool && npm ci","cd 05_開発/tool && .venv/bin/pip install pandas",
 "cd 05_開発/tool && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt",f"cd {EXT} && npm install",f"npm --prefix {EXT} install",
 f"git -C {EXT} checkout -b ai/x",f"cd {EXT} && git add -A && git commit -m x","cd 05_開発/tool && git init"]
dev_bad=["npm install x","cd 05_開発/tool && npm install -g x","cd 05_開発/tool && python3 -m pip install x","cd 05_開発/tool && pip install x",
 "cd /tmp && npm install","cd 05_開発/tool && git push","cd 05_開発/tool && rm -rf node_modules","cd 05_開発/tool && npm install && cd ../.. && npm install x",
 f"cd {EXT} && git push origin main","cd 05_開発/tool && brew install x","cd 05_開発/tool && sudo npm install"]
dev_good+=["cd 05_開発/tool && source .venv/bin/activate && pip install pandas","(cd 05_開発/tool && npm install)",
 "cd 05_開発/tool && .venv/bin/python -m pip install x"]
dev_bad+=["cd 05_開発/tool && npm install --location=global foo","cd 05_開発/tool && npm install --prefix=/other","cd 05_開発/tool && gem install foo",
 "cd 05_開発/tool && .venv/bin/pip install --target /other x","cd 05_開発/tool && echo x/venv/bin/; pip install foo",
 "npm install; echo hi","(npm install)","cd 05_開発/tool && cd /tmp && npm install"]
# 今いる場所が開発の置き場所でも、cd の行き先が外ならインストールは止める
def run_cwd(cmd,cwd):
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":"Bash","tool_input":{"command":cmd},"cwd":cwd}),capture_output=True,text=True,cwd=R,env={**os.environ,"CLAUDE_PROJECT_DIR":R})
    return "STOP" if "deny" in p.stdout else "pass"
for c in ["cd /other && npm install","cd .. && cd .. && npm install"]:
    if run_cwd(c,EXT)!="STOP": fail+=1; print("DEV MISS (cwd)",repr(c))
if run_cwd("npm install",EXT)!="pass": fail+=1; print("DEV FALSEPOS (cwd)","npm install")
# プラグインのコピー（~/.claude/plugins/）は誰でも止める。プラグインの元は maintainer だけ通す
SRC=tempfile.mkdtemp(prefix="ngsrc_"); os.makedirs(os.path.join(SRC,"plugins","x",".claude-plugin"),exist_ok=True)
open(os.path.join(SRC,"plugins","x",".claude-plugin","plugin.json"),"w").write("{}")
CACHE=os.path.expanduser("~/.claude/plugins/cache/x/ai-bunshin/0.0.0/rules/r.md")
def cfg(maint):
    json.dump({"maintainer":maint,"dev":{"default_mode":"local","projects":[{"name":"ext","mode":"git","path":EXT}]}},open(os.path.join(R,"設定","config.json"),"w"))
cfg(False)
for tool,inp,want in [("Write",{"file_path":CACHE},"STOP"),("Edit",{"file_path":os.path.join(SRC,"plugins","x","rules","r.md")},"STOP"),
                      ("Bash",{"command":"echo x > ~/.claude/plugins/cache/x/r.md"},"STOP"),("Bash",{"command":"sed -i '' s/a/b/ ~/.claude/plugins/cache/x/r.md"},"STOP"),
                      ("Bash",{"command":"cat ~/.claude/plugins/cache/x/r.md"},"pass")]:
    if run(tool,inp)!=want: fail+=1; print("PLUGIN(non-maintainer)",want,tool,inp)
SRCF=os.path.join(SRC,"plugins","x","rules","r.md")
for c,want in [("python3 -c \"open('"+os.path.expanduser("~")+"/.claude/plugins/a','w').write('x')\"","STOP"),
               ("cd ~/.claude/plugins && cp x .","STOP"),("cp -t ~/.claude/plugins x","STOP"),("install x ~/.claude/plugins/a","STOP"),
               ("touch ~/.claude/plugins/a","STOP"),("mv ~/.claude/plugins/a b","STOP"),("cp x ../../.claude/plugins/a","STOP"),
               ("echo x > "+SRCF,"STOP"),("cp x "+SRCF,"STOP"),
               ("cat ~/.claude/plugins/a","pass"),("ls ~/.claude/plugins/","pass"),("diff ~/.claude/plugins/a b","pass"),
               ("cp ~/.claude/plugins/a ./b","pass"),("cat "+SRCF,"pass")]:
    if run("Bash",{"command":c})!=want: fail+=1; print("PLUGIN(bash, non-maintainer)",want,repr(c))
# 本人の許可する例外（ng_allow）でも、プラグインのコピーの保護は外れない
json.dump({"maintainer":False,"ng_allow":[".*"]},open(os.path.join(R,"設定","config.json"),"w"))
if run("Write",{"file_path":CACHE})!="STOP": fail+=1; print("PLUGIN ng_allow で外れた")
cfg(True)
for c,want in [("echo x > "+SRCF,"pass"),("touch ~/.claude/plugins/a","STOP")]:
    if run("Bash",{"command":c})!=want: fail+=1; print("PLUGIN(bash, maintainer)",want,repr(c))
for tool,inp,want in [("Write",{"file_path":CACHE},"STOP"),("Edit",{"file_path":os.path.join(SRC,"plugins","x","rules","r.md")},"pass")]:
    if run(tool,inp)!=want: fail+=1; print("PLUGIN(maintainer)",want,tool,inp)
cfg(False)
print("## DEV")
for c in dev_good:
    if run("Bash",{"command":c})!="pass": fail+=1; print("DEV FALSEPOS",repr(c))
for c in dev_bad:
    if run("Bash",{"command":c})!="STOP": fail+=1; print("DEV MISS",repr(c))
print("## 本人のフォルダの外・中")
def run_at(tool,inp,base,env_dir=True,payload_cwd=True):
    """base で動いている想定（CLAUDE_PROJECT_DIR・payload の cwd・プロセスの cwd をそこにそろえる）。"""
    env={k:v for k,v in os.environ.items() if k!="CLAUDE_PROJECT_DIR"}
    if env_dir: env["CLAUDE_PROJECT_DIR"]=base
    pl={"tool_name":tool,"tool_input":inp}
    if payload_cwd: pl["cwd"]=base
    p=subprocess.run(["python3",G],input=json.dumps(pl),capture_output=True,text=True,cwd=base,env=env)
    return "STOP" if "deny" in p.stdout else "pass"
OUT=tempfile.mkdtemp(prefix="ngout_")  # 設定なし＝ほかのプロジェクト
def mk_owner(marks):
    d=tempfile.mkdtemp(prefix="ngmark_")
    for m in marks:
        os.makedirs(os.path.dirname(os.path.join(d,m)),exist_ok=True); open(os.path.join(d,m),"w").write("{}")
    return d
M_CFG="設定/config.json"; M_TASK="00_タスク管理/data/tasks.json"; M_RULE=".claude/rules/ai-bunshin-common.md"
for c in ["rm x","git push","npm install x","curl https://example.com","sudo ls","git clean -fd","pip install x","ssh h","gh pr create","> 03_インプット/x","git reset --hard"]:
    if run_at("Bash",{"command":c},OUT)!="pass": fail+=1; print("OUTSIDE FALSEPOS",repr(c),OUT)
    # 印がどれか1つでもあれば本人のフォルダ（片方を動かして見張りを外す抜け道を塞ぐ）。config だけ・tasks.json だけ・共通ルールの写しだけ
    for marks in ([M_CFG],[M_TASK],[M_RULE]):
        d=mk_owner(marks)
        if run_at("Bash",{"command":c},d)!="STOP": fail+=1; print("HALF MISS",repr(c),marks)
for t,p in [("Write",OUT+"/03_インプット/x.csv"),("Write",OUT+"/.claude/settings.json"),("Edit",os.path.join(SRC,"plugins","x","rules","r.md"))]:
    if run_at(t,{"file_path":p},OUT)!="pass": fail+=1; print("OUTSIDE PATH FALSEPOS",t,p)
# 本人のフォルダの外でも、プラグインのコピー（~/.claude/plugins/）への書き込みは止める（読むだけは通す）
for tool,inp,want in [("Write",{"file_path":CACHE},"STOP"),("Edit",{"file_path":CACHE},"STOP"),
                      ("Bash",{"command":"echo x > ~/.claude/plugins/cache/x/r.md"},"STOP"),("Bash",{"command":"touch ~/.claude/plugins/a"},"STOP"),
                      ("Bash",{"command":"sed -i '' s/a/b/ ~/.claude/plugins/cache/x/r.md"},"STOP"),
                      ("Bash",{"command":"cat ~/.claude/plugins/cache/x/r.md"},"pass"),("Bash",{"command":"ls ~/.claude/plugins/"},"pass")]:
    if run_at(tool,inp,OUT)!=want: fail+=1; print("OUTSIDE PLUGIN COPY",want,tool,inp)
# 本人のフォルダの中、その下（05_開発/x）、環境変数なし・cwd だけの場合は、今までどおり止める
os.makedirs(os.path.join(R,"05_開発","x"),exist_ok=True)
SUB=os.path.join(R,"05_開発","x")
for base,kw in [(R,{}),(SUB,{}),(SUB,{"env_dir":False}),(R,{"env_dir":False,"payload_cwd":False})]:
    for c in ["rm x","git push","curl https://example.com","sudo ls"]:
        if run_at("Bash",{"command":c},base,**kw)!="STOP": fail+=1; print("INSIDE MISS",repr(c),base.replace(R,"<R>"),kw)
    if run_at("Write",{"file_path":R+"/03_インプット/x.csv"},base,**kw)!="STOP": fail+=1; print("INSIDE PATH MISS",base.replace(R,"<R>"),kw)
    if run_at("Bash",{"command":"ls -la"},base,**kw)!="pass": fail+=1; print("INSIDE FALSEPOS ls",base.replace(R,"<R>"),kw)
# 下のフォルダで動いていても、相対パスの基準は見つかった本人のフォルダ
if run_at("Write",{"file_path":os.path.join(SUB,"..","..","03_インプット","a")},SUB)!="STOP": fail+=1; print("INSIDE PATH (sub, ..)")
if run_at("Bash",{"command":"cd 05_開発/x && npm install"},R)!="pass": fail+=1; print("INSIDE DEV FALSEPOS (npm install in 05_開発/x)")
if run_at("Bash",{"command":"npm install"},SUB)!="pass": fail+=1; print("INSIDE DEV FALSEPOS (cwd=05_開発/x)")
# 印・設定・タスクの正本を動かす・名前を変える操作は止める（動かすと見張りが外れるため）
print("## 印の移動")
for c in ["mv 設定 設定_old","mv 設定/config.json 設定/c.json","git mv 設定/config.json 設定/c.json","mv 00_タスク管理/data/tasks.json 00_タスク管理/data/tasks.bak",
          "mv 00_タスク管理 x","mv 00_タスク管理/data x","mv x 設定/config.json","mv ./設定 /tmp/x","mv \"設定\" /tmp/x","cd 05_開発 && mv ../設定 x",
          "mv .claude/rules/ai-bunshin-common.md x","rename s/a/b/ 設定/config.json",
          "python3 -c \"import os;os.rename('設定','x')\"","python3 -c \"import shutil;shutil.move('00_タスク管理/data/tasks.json','x')\"",
          "python3 -c \"from pathlib import Path;Path('設定').rename('x')\"","python3 -c \"import os;os.replace('設定/config.json','x')\"",
          "mv . /tmp/moved","mv "+R+" /tmp/moved","mv "+os.path.dirname(R)+" /tmp/moved2","mv -t /tmp "+R]:
    if run_at("Bash",{"command":c},R)!="STOP": fail+=1; print("MOVE MISS",repr(c))
for c in ["mv 02_成果物/a 02_成果物/b","mv 02_成果物/a.md .","mv 02_成果物/a.md ..","ls 設定","cat 設定/config.json","cp 設定/config.json 02_成果物/config.bak","mv 02_成果物/設定_old.md 02_成果物/x.md",
          "python3 -c \"print('設定'.replace('a','b'))\"","python3 -c \"print(open('設定/config.json').read())\"","git mv 02_成果物/a 02_成果物/b","mv 05_開発/x 05_開発/y"]:
    if run_at("Bash",{"command":c},R)!="pass": fail+=1; print("MOVE FALSEPOS",repr(c))
# リンクを解かない道でも本人のフォルダを見つける（本人のフォルダの下のリンクが外を指していても止める）
print("## リンク")
LNKTARGET=tempfile.mkdtemp(prefix="nglink_"); LNK=os.path.join(R,"05_開発","ext")
if not os.path.lexists(LNK): os.symlink(LNKTARGET,LNK)
for c in ["git push","rm x","curl https://example.com"]:
    for kw in ({},{"env_dir":False}):
        if run_at("Bash",{"command":c},LNK,**kw)!="STOP": fail+=1; print("SYMLINK MISS",repr(c),kw)
# 外で始めたセッションでも、操作の中のパスが本人のフォルダを指すなら、その本人のフォルダを基準に判定する
print("## 外からのパス")
HOMED=tempfile.mkdtemp(prefix="nghome_"); OWN=os.path.join(HOMED,"own"); os.makedirs(os.path.join(HOMED,"sub"))
for m in (M_CFG,M_TASK): os.makedirs(os.path.dirname(os.path.join(OWN,m)),exist_ok=True); open(os.path.join(OWN,m),"w").write("{}")
def run_home(tool,inp,base):
    env={k:v for k,v in os.environ.items() if k!="CLAUDE_PROJECT_DIR"}; env["HOME"]=HOMED
    p=subprocess.run(["python3",G],input=json.dumps({"tool_name":tool,"tool_input":inp,"cwd":base}),capture_output=True,text=True,cwd=base,env=env)
    return "STOP" if "deny" in p.stdout else "pass"
for tool,inp,want in [
    ("Bash",{"command":"cd /tmp && rm -rf "+OWN+"/03_インプット"},"STOP"),("Bash",{"command":"cd "+HOMED+" && rm -rf "+OWN+"/03_インプット"},"STOP"),
    ("Bash",{"command":"rm -rf ~/own/03_インプット"},"STOP"),("Bash",{"command":"rm -rf $HOME/own/03_インプット"},"STOP"),
    ("Bash",{"command":"rm -rf \"$HOME/own/03_インプット\""},"STOP"),("Bash",{"command":"rm -rf ${HOME}/own"},"STOP"),
    ("Bash",{"command":"git -C ~/own push"},"STOP"),("Bash",{"command":"echo x > "+OWN+"/03_インプット/a"},"STOP"),
    ("Bash",{"command":"mv "+OWN+"/設定 /tmp/x"},"STOP"),("Bash",{"command":"mv ~/own/00_タスク管理/data/tasks.json /tmp/x"},"STOP"),
    ("Write",{"file_path":OWN+"/03_インプット/a.csv"},"STOP"),("Write",{"file_path":OWN+"/.claude/settings.json"},"STOP"),
    ("Edit",{"file_path":OWN+"/.claude/hooks/x.sh"},"STOP"),("MultiEdit",{"file_path":OWN+"/03_インプット/a"},"STOP"),
    ("NotebookEdit",{"notebook_path":OWN+"/03_インプット/a.ipynb"},"STOP"),
    ("Write",{"file_path":"../own/03_インプット/a"},"STOP"),
    ("Bash",{"command":"rm -rf build"},"pass"),("Bash",{"command":"git push"},"pass"),("Bash",{"command":"curl https://example.com"},"pass"),
    ("Bash",{"command":"rm -rf /tmp/build ~/other/x"},"pass"),("Bash",{"command":"cat ~/own/設定/config.json"},"pass"),
    ("Bash",{"command":"ls ~/own/03_インプット"},"pass"),("Bash",{"command":"echo x > ~/own/02_成果物/a.md"},"pass"),
    ("Write",{"file_path":OWN+"/02_成果物/a.md"},"pass"),("Write",{"file_path":"/tmp/x.md"},"pass"),("Write",{"file_path":HOMED+"/other/03_インプット/a"},"pass")]:
    if run_home(tool,inp,os.path.join(HOMED,"sub") if inp.get("file_path","").startswith("..") else "/tmp")!=want: fail+=1; print("FROM-OUTSIDE",want,tool,inp)
# 見張りの入力が壊れていたら：本人のフォルダの中なら止める、外なら通す（例外で落ちて通る側にならない）
print("## 壊れた入力")
def run_raw(text,base):
    env={k:v for k,v in os.environ.items() if k!="CLAUDE_PROJECT_DIR"}; env["CLAUDE_PROJECT_DIR"]=base
    p=subprocess.run(["python3",G],input=text,capture_output=True,text=True,cwd=base,env=env)
    return ("STOP" if "deny" in p.stdout else "pass"), p.returncode
for text in ["[]","null","123","\"str\"","{broken","","{\"tool_name\":\"Bash\",\"tool_input\":\"rm x\",\"cwd\":5}","{\"tool_name\":\"Write\",\"tool_input\":[1]}"]:
    for base,want in ((R,"STOP"),(SUB,"STOP"),(OUT,"pass")):
        got,rc=run_raw(text,base)
        if got!=want or rc!=0: fail+=1; print("BROKEN INPUT",repr(text),base.replace(R,"<R>"),got,rc,"want",want)
print(f"失敗 {fail} 件"); sys.exit(1 if fail else 0)
