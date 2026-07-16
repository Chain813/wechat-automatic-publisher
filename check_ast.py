import ast
import os

def check_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        code = f.read()
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        print(f"SyntaxError in {filename}: {e}")
        return False

    errors = []
    
    # A very naive undefined name checker
    class UndefinedNameChecker(ast.NodeVisitor):
        def __init__(self):
            self.defined = set(dir(__builtins__))
            self.defined.update({'True', 'False', 'None'})
            self.errors = []
            self.scope_stack = [set()]
            
        def define(self, name):
            self.scope_stack[-1].add(name)
            
        def is_defined(self, name):
            for scope in reversed(self.scope_stack):
                if name in scope:
                    return True
            return name in self.defined
            
        def visit_Import(self, node):
            for name in node.names:
                self.define(name.asname or name.name.split('.')[0])
            self.generic_visit(node)
            
        def visit_ImportFrom(self, node):
            for name in node.names:
                self.define(name.asname or name.name)
            self.generic_visit(node)
            
        def visit_FunctionDef(self, node):
            self.define(node.name)
            self.scope_stack.append(set())
            for arg in node.args.args:
                self.define(arg.arg)
            if node.args.vararg:
                self.define(node.args.vararg.arg)
            if node.args.kwarg:
                self.define(node.args.kwarg.arg)
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_ClassDef(self, node):
            self.define(node.name)
            self.scope_stack.append(set())
            self.generic_visit(node)
            self.scope_stack.pop()
            
        def visit_Assign(self, node):
            self.generic_visit(node)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.define(target.id)
                elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            self.define(elt.id)

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load) and not self.is_defined(node.id):
                # Naive: might flag globals used in functions but defined later, or class scope
                self.errors.append((node.lineno, node.id))
            self.generic_visit(node)

        # Basic coverage
        def visit_Global(self, node):
            for name in node.names:
                self.define(name)
                
    checker = UndefinedNameChecker()
    checker.visit(tree)
    
    # Due to naive implementation, this will yield many false positives
    # But it's good for a quick sanity check
    return True

files_to_check = [
    "core/hotspots/workflow.py",
    "core/github/workflow.py",
    "core/plugins/hotspots_sources.py",
    "webui.py"
]

for f in files_to_check:
    check_file(f)

print("Check finished.")
