export function MutationError({ mutation }: { mutation: { error: Error | null } }) {
  return mutation.error ? (
    <p className="form-error" role="alert">
      {mutation.error.message}
    </p>
  ) : null;
}
