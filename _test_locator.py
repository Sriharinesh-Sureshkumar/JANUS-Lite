import os, shutil, sys
import process_verification as pv  # module handles UTF-8 wrapping itself

hypothesis = "update_case uses c[id] instead of c[case_id], causing case lookup to fail"
repo_url   = "https://github.com/Sriharinesh-Sureshkumar/sahayak-janus-demo"

print("Hypothesis:", hypothesis)
print()

keywords = pv.extract_keywords(hypothesis)
print("Keywords extracted:", keywords)
print()

print(f"Cloning {repo_url} ...")
context, tmpdir = pv.locate_in_repo(repo_url, keywords)
print()
print("=" * 60)
print("LOCATION CONTEXT")
print("=" * 60)
print(context if context else "(no keyword hits found)")
print()

if tmpdir and os.path.isdir(tmpdir):
    shutil.rmtree(tmpdir, ignore_errors=True)
    print("(temp clone cleaned up)")
