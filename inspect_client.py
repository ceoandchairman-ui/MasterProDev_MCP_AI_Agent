#!/usr/bin/env python3
"""
Script to inspect InferenceClient attributes and methods
"""

from huggingface_hub import InferenceClient
import inspect

def main():
    print("=" * 80)
    print("INFERECENCECLIENT INSPECTION SCRIPT")
    print("=" * 80)
    
    # Create an instance
    client = InferenceClient()
    
    # 1. Type and class info
    print("\n1. TYPE INFORMATION")
    print("-" * 80)
    print(f"Type: {type(client)}")
    print(f"Class: {client.__class__.__name__}")
    print(f"Module: {client.__class__.__module__}")
    
    # 2. Instance attributes (current values)
    print("\n2. INSTANCE ATTRIBUTES (Current Values)")
    print("-" * 80)
    attrs = vars(client)
    for key, value in attrs.items():
        print(f"  {key}: {value}")
    
    # 3. All methods and attributes
    print("\n3. ALL ATTRIBUTES & METHODS (dir() output)")
    print("-" * 80)
    all_items = dir(client)
    print(f"Total items: {len(all_items)}")
    
    # Separate public from private
    public = [x for x in all_items if not x.startswith('_')]
    private = [x for x in all_items if x.startswith('_') and not x.startswith('__')]
    dunder = [x for x in all_items if x.startswith('__')]
    
    print(f"\nPublic methods/attributes ({len(public)}):")
    for item in sorted(public):
        print(f"  - {item}")
    
    print(f"\nPrivate methods/attributes ({len(private)}):")
    for item in sorted(private):
        print(f"  - {item}")
    
    print(f"\nDunder methods ({len(dunder)}):")
    for item in sorted(dunder)[:10]:  # Show first 10
        print(f"  - {item}")
    print(f"  ... and {len(dunder) - 10} more")
    
    # 4. Public methods signature
    print("\n4. PUBLIC METHODS SIGNATURES")
    print("-" * 80)
    for method_name in sorted(public):
        if not method_name.isupper():  # Skip constants
            try:
                method = getattr(client, method_name)
                if callable(method):
                    sig = inspect.signature(method)
                    print(f"\n{method_name}{sig}")
            except Exception as e:
                print(f"\n{method_name}: (unable to inspect)")
    
    # 5. Feature extraction method details
    print("\n5. FEATURE_EXTRACTION METHOD DETAILS")
    print("-" * 80)
    try:
        sig = inspect.signature(client.feature_extraction)
        print(f"Signature: {sig}")
        print(f"\nDocstring:")
        if client.feature_extraction.__doc__:
            print(client.feature_extraction.__doc__[:500])
    except Exception as e:
        print(f"Error: {e}")
    
    # 6. Chat completion method details
    print("\n6. CHAT_COMPLETION METHOD DETAILS")
    print("-" * 80)
    try:
        sig = inspect.signature(client.chat_completion)
        print(f"Signature: {sig}")
        print(f"\nDocstring:")
        if client.chat_completion.__doc__:
            print(client.chat_completion.__doc__[:500])
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "=" * 80)
    print("INSPECTION COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()
