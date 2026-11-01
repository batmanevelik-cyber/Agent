// Single-file, code-only updater for an existing Alpha50X installation.
package main

import (
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

//go:embed alpha50x_public_update.py
var payload []byte
var payloadDigest string

func payloadOK() bool {
	sum := sha256.Sum256(payload)
	return len(payloadDigest) == 64 && hex.EncodeToString(sum[:]) == payloadDigest
}

func choosePython(target string) (string, error) {
	raw, err := os.ReadFile(filepath.Join(target, "current.json"))
	if err != nil { return "", errors.New("existing Alpha50X installation not found") }
	var current struct { Python string `json:"python"` }
	if json.Unmarshal(raw, &current) != nil || current.Python == "" { return "", errors.New("invalid installation pointer") }
	info, err := os.Stat(current.Python)
	if err != nil || info.IsDir() { return "", errors.New("existing Python interpreter is unavailable") }
	return current.Python, nil
}

func requestStop(target string) error {
	raw, err := json.Marshal(map[string]interface{}{"action":"shutdown_for_update", "requested_ms":time.Now().UnixMilli()})
	if err != nil { return err }
	return os.WriteFile(filepath.Join(target,"data","update-request.json"), raw, 0600)
}

const probe = `import os,sys,time
from pathlib import Path
root=Path(sys.argv[1]);deadline=time.monotonic()+float(sys.argv[2])
def free(path):
    if not path.exists():return True
    try:
        with path.open('r+b') as f:
            f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(f.fileno(),fcntl.LOCK_UN)
        return True
    except OSError:return False
while True:
    if all(free(root/'data'/name) for name in ('service.lock','background-launcher.lock')):break
    if time.monotonic()>=deadline:sys.exit(3)
    time.sleep(.1)
`

func waitForPrevious(python, target string, timeout time.Duration, output io.Writer) error {
	cmd := exec.Command(python,"-c",probe,target,fmt.Sprint(timeout.Seconds()))
	cmd.Stdout=output;cmd.Stderr=output
	return cmd.Run()
}

func runUpdate(python, script, target string, output io.Writer) error {
	cmd:=exec.Command(python,script,"--target",target,"--use-current-python")
	cmd.Stdout=output;cmd.Stderr=output
	return cmd.Run()
}

func perform(target string, start bool, output io.Writer) error {
	python,err:=choosePython(target);if err!=nil{return err}
	if err=os.MkdirAll(filepath.Join(target,"data"),0700);err!=nil{return err}
	if err=requestStop(target);err!=nil{return err}
	request:=filepath.Join(target,"data","update-request.json");defer os.Remove(request)
	if err=waitForPrevious(python,target,110*time.Second,output);err!=nil{return errors.New("previous service is still running; update has not been installed")}
	f,err:=os.CreateTemp(filepath.Join(target,"data"),"code-update-*.py");if err!=nil{return err}
	script:=f.Name();defer os.Remove(script)
	_,writeErr:=f.Write(payload);closeErr:=f.Close();if writeErr!=nil{return writeErr};if closeErr!=nil{return closeErr}
	if err=runUpdate(python,script,target,output);err!=nil{return errors.New("update validation failed; previous installation is retained")}
	if err=os.Remove(request);err!=nil&&!os.IsNotExist(err){return err}
	if !start{return nil}
	python,err=choosePython(target);if err!=nil{return err}
	cmd:=exec.Command(python,filepath.Join(target,"start_alpha50x.py"),"--background","--auto-paper-all")
	cmd.Stdout=output;cmd.Stderr=output
	return cmd.Run()
}

func main() {
	verify:=flag.Bool("verify-only",false,"Verify the embedded code-only updater")
	target:=flag.String("target",filepath.Join(os.Getenv("LOCALAPPDATA"),"Alpha50X Unified"),"Existing Alpha50X installation")
	noStart:=flag.Bool("no-start",false,"Install without starting the terminal")
	flag.Parse()
	if !payloadOK(){fmt.Fprintln(os.Stderr,"Embedded updater checksum failed");os.Exit(1)}
	if *verify{fmt.Println("PASS: embedded code-only updater checksum");return}
	fmt.Println("Alpha50X - PAPER code update")
	logdir:=filepath.Join(*target,"data","logs")
	if err:=os.MkdirAll(logdir,0700);err!=nil{fmt.Fprintln(os.Stderr,"Cannot create local setup log");os.Exit(1)}
	file,err:=os.OpenFile(filepath.Join(logdir,"setup-"+time.Now().Format("20060102-150405")+".log"),os.O_CREATE|os.O_WRONLY|os.O_EXCL,0600)
	if err!=nil{fmt.Fprintln(os.Stderr,"Cannot create local setup log");os.Exit(1)}
	output:=io.MultiWriter(os.Stdout,file)
	err=perform(*target,!*noStart,output);file.Close()
	if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(1)}
	fmt.Println("Update complete. Portfolio and local connections retained.")
}
