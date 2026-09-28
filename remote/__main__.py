import sys
from ai_exp_remote.rpc import main
if len(sys.argv)<2 or sys.argv[1]=='rpc':main()
elif sys.argv[1]=='daemon':
    from ai_exp_remote.runtime import daemon
    daemon(sys.argv[2])
elif sys.argv[1]=='attempt':
    from ai_exp_remote.runner import execute_attempt
    execute_attempt(sys.argv[2])
else:raise SystemExit('Unknown command')
